"""knowledge.py — offline-first answer engine for J.A.R.V.I.S.

Takes everyday Q&A from "basic" to genuinely useful without any API key:

  calculate("18% of 4500")      -> safe arithmetic, %, roots, constants
  convert_units("32C to F")      -> temp / length / weight offline;
                                    currency online (free, keyless) w/ fallback
  define_word("serendipity")     -> dictionaryapi.dev (free, keyless, cached)
  get_joke() / get_fact()        -> curated rotation, never repeats back-to-back
  instant_answer("capital of...") -> DuckDuckGo instant answers (keyless)

Every function returns {"status", "message", ...} and NEVER raises.
"""
from __future__ import annotations

import ast
import json
import math
import operator as _op
import os
import random
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_BASE, "backend", "data")
_ROTATION_PATH = os.path.join(_DATA_DIR, "knowledge_rotation.json")

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")


# ── tiny JSON helpers ─────────────────────────────────────────────────────────
def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as h:
            return json.load(h)
    except (OSError, ValueError, TypeError):
        return default


def _write_json(path: str, value: Any) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as h:
            json.dump(value, h, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def _http_get_json(url: str, timeout: float = 6.0) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


# ── calculator ────────────────────────────────────────────────────────────────
_SAFE_BINOPS = {
    ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
    ast.Div: _op.truediv, ast.Mod: _op.mod, ast.Pow: _op.pow,
    ast.FloorDiv: _op.floordiv,
}
_SAFE_UNARY = {ast.UAdd: _op.pos, ast.USub: _op.neg}
_SAFE_FUNCS = {
    "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log10, "ln": math.log, "abs": abs, "round": round,
    "floor": math.floor, "ceil": math.ceil, "factorial": math.factorial,
}
_SAFE_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
        return _SAFE_BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY:
        return _SAFE_UNARY[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _SAFE_FUNCS and len(node.args) == 1 and not node.keywords:
        return float(_SAFE_FUNCS[node.func.id](_eval_node(node.args[0])))
    if isinstance(node, ast.Name) and node.id in _SAFE_CONSTS:
        return float(_SAFE_CONSTS[node.id])
    raise ValueError("unsupported")


def _fmt_num(x: float) -> str:
    if not math.isfinite(x):
        raise ValueError("non-finite")
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return s if len(s) <= 16 else f"{x:.4g}"


_PERCENT_OF_RE = re.compile(
    r"(?P<a>\d+(?:\.\d+)?)\s*%\s*of\s*(?P<b>\d+(?:\.\d+)?)", re.I)
_PERCENT_ADD_RE = re.compile(
    r"(?P<b>\d+(?:\.\d+)?)\s*(?P<op>plus|\+|minus|\-)\s*(?P<a>\d+(?:\.\d+)?)\s*%", re.I)


def calculate(raw: str) -> Dict[str, Any]:
    """Safe arithmetic. Understands '18% of 4500', 'sqrt(144)', '2^10', etc."""
    text = (raw or "").strip()
    if not text:
        return {"status": "error", "message": "Give me a sum to crunch — e.g. 18% of 4500."}
    work = text.lower()
    work = re.sub(r"\b(what(?:'s| is)|calculate|compute|evaluate|solve|please)\b", " ", work)
    work = work.replace("^", "**").replace("×", "*").replace("÷", "/")
    if re.search(r"\d\s*x\s*\d", work):
        work = work.replace("x", "*")
    work = re.sub(r"\s+", " ", work).strip(" =?")
    if not work:
        return {"status": "error", "message": "Give me a sum to crunch — e.g. 18% of 4500."}

    # "18% of 4500"
    m = _PERCENT_OF_RE.search(work)
    if m:
        try:
            val = float(m.group("a")) / 100.0 * float(m.group("b"))
            return {"status": "success", "expression": m.group(0),
                    "result": _fmt_num(val),
                    "message": f"{m.group('a')}% of {_fmt_num(float(m.group('b')))} is {_fmt_num(val)}."}
        except (ValueError, ZeroDivisionError):
            pass
    # "4500 plus 18%" / "4500 minus 18%"
    m = _PERCENT_ADD_RE.search(work)
    if m:
        try:
            b, a = float(m.group("b")), float(m.group("a"))
            val = b + a / 100.0 * b if m.group("op") in ("plus", "+") else b - a / 100.0 * b
            return {"status": "success", "expression": m.group(0),
                    "result": _fmt_num(val),
                    "message": f"{_fmt_num(b)} {'plus' if m.group('op') in ('plus', '+') else 'minus'} {m.group('a')}% is {_fmt_num(val)}."}
        except (ValueError, ZeroDivisionError):
            pass
    # Lone trailing "%"  ("18%" -> 0.18)
    if re.fullmatch(r"\d+(?:\.\d+)?\s*%", work):
        try:
            val = float(work.rstrip("% ").strip()) / 100.0
            return {"status": "success", "expression": text.strip(),
                    "result": _fmt_num(val), "message": f"That's {_fmt_num(val)}."}
        except ValueError:
            pass
    # General safe expression
    if not re.fullmatch(r"[0-9+\-*/().% \t]*|[a-z]+\([^()]*\)|[a-z0-9+\-*/().% \t]*", work):
        return {"status": "error",
                "message": "I only crunch numbers — try something like (12 + 8) * 3 or sqrt(144)."}
    if re.search(r"__|import|lambda|exec|eval|open|os|sys", work):
        return {"status": "error", "message": "That doesn't look like arithmetic to me."}
    try:
        val = _eval_node(ast.parse(work, mode="eval"))
        return {"status": "success", "expression": work,
                "result": _fmt_num(val),
                "message": f"That works out to {_fmt_num(val)}."}
    except ZeroDivisionError:
        return {"status": "error", "message": "Division by zero — even I can't do that one."}
    except (ValueError, SyntaxError, OverflowError, TypeError):
        return {"status": "error",
                "message": "I couldn't parse that sum — try something like (12 + 8) * 3."}


# ── unit + currency conversion ────────────────────────────────────────────────
_LEN_M = {"mm": 0.001, "cm": 0.01, "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0,
          "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0,
          "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
          "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
          "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
          "mi": 1609.344, "mile": 1609.344, "miles": 1609.344}
_WT_KG = {"mg": 1e-6, "g": 1.0e-3, "gram": 1e-3, "grams": 1e-3, "kg": 1.0,
          "kilogram": 1.0, "kilograms": 1.0, "oz": 0.028349523125,
          "ounce": 0.028349523125, "ounces": 0.028349523125,
          "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237,
          "ton": 1000.0, "tons": 1000.0, "tonne": 1000.0, "tonnes": 1000.0}

_CCY_SYM = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}
_CCY_WORD = {"dollar": "USD", "dollars": "USD", "usd": "USD",
             "euro": "EUR", "euros": "EUR", "eur": "EUR",
             "pound": "GBP", "pounds": "GBP", "gbp": "GBP",
             "yen": "JPY", "jpy": "JPY", "yuan": "CNY", "cny": "CNY",
             "rupee": "INR", "rupees": "INR", "inr": "INR", "rs": "INR",
             "aed": "AED", "dirham": "AED", "sar": "SAR", "riyal": "SAR"}

_CONVERT_RE = re.compile(
    r"(?P<amt>\d+(?:\.\d+)?)\s*(?P<frm>[A-Za-z$€£¥₹]{1,10})\.?\s+"
    r"(?:to|in|into|=)\s+(?P<to>[A-Za-z$€£¥₹]{1,10})\.?", re.I)


def _resolve_ccy(token: str) -> str:
    t = (token or "").strip()
    if t in _CCY_SYM:
        return _CCY_SYM[t]
    low = t.lower()
    if low in _CCY_WORD:
        return _CCY_WORD[low]
    if re.fullmatch(r"[A-Za-z]{3}", t):
        return t.upper()
    return ""


def convert_units(raw: str) -> Dict[str, Any]:
    """Convert temperature / length / weight offline; currency online."""
    text = (raw or "").strip()
    m = _CONVERT_RE.search(text)
    if not m:
        return {"status": "error",
                "message": "Tell me like: 32C to F, 5 km to miles, or 100 USD to INR."}
    try:
        amt = float(m.group("amt"))
    except ValueError:
        return {"status": "error", "message": "I couldn't read the amount there."}
    frm_raw, to_raw = m.group("frm"), m.group("to")
    frm, to = frm_raw.lower(), to_raw.lower()

    # 1. Temperature (normalize via Celsius)
    _TKEY = {"c": "c", "celsius": "c", "centigrade": "c",
             "f": "f", "fahrenheit": "f",
             "k": "k", "kelvin": "k"}
    fkey, tkey = _TKEY.get(frm), _TKEY.get(to)
    if fkey or tkey:
        if fkey and tkey:
            try:
                c = amt if fkey == "c" else ((amt - 32) * 5 / 9 if fkey == "f" else amt - 273.15)
                out = c if tkey == "c" else (c * 9 / 5 + 32 if tkey == "f" else c + 273.15)
                unit_in = {"c": "°C", "f": "°F", "k": "K"}[fkey]
                unit_out = {"c": "°C", "f": "°F", "k": "K"}[tkey]
                return {"status": "success", "result": out,
                        "message": f"{_fmt_num(amt)}{unit_in} is {_fmt_num(out)}{unit_out}."}
            except (ValueError, OverflowError):
                pass
        return {"status": "error", "message": "Temperature needs C, F or K — e.g. 32C to F."}

    # 2. Length / weight (offline tables)
    for table, label in ((_LEN_M, "length"), (_WT_KG, "weight")):
        if frm in table and to in table:
            try:
                out = amt * table[frm] / table[to]
                return {"status": "success", "result": out,
                        "message": f"{_fmt_num(amt)} {frm_raw} is {_fmt_num(out)} {to_raw}."}
            except (ValueError, ZeroDivisionError):
                return {"status": "error", "message": "That conversion slipped through my fingers."}

    # 3. Currency (online, free keyless API)
    fccy, tccy = _resolve_ccy(frm_raw), _resolve_ccy(to_raw)
    if fccy and tccy:
        data = _http_get_json(
            f"https://api.exchangerate.host/convert?from={fccy}&to={tccy}&amount={amt}")
        if data and isinstance(data.get("result"), (int, float)):
            out = float(data["result"])
            return {"status": "success", "result": out,
                    "message": f"{_fmt_num(amt)} {fccy} is about {_fmt_num(out)} {tccy} at today's rate."}
        data = _http_get_json(f"https://open.er-api.com/v6/latest/{fccy}")
        try:
            rate = (data or {}).get("rates", {}).get(tccy)
            if rate:
                out = amt * float(rate)
                return {"status": "success", "result": out,
                        "message": f"{_fmt_num(amt)} {fccy} is about {_fmt_num(out)} {tccy} at today's rate."}
        except (TypeError, ValueError):
            pass
        return {"status": "error",
                "message": "I can't reach the exchange-rate service right now — check your connection and try again."}
    return {"status": "error",
            "message": "I convert temperature, length, weight and money — e.g. 5 km to miles."}


# ── dictionary ────────────────────────────────────────────────────────────────
_DEFINE_CACHE: Dict[str, Dict[str, Any]] = {}


def define_word(raw: str) -> Dict[str, Any]:
    """Short dictionary entry via dictionaryapi.dev (free, keyless, cached)."""
    words = _WORD_RE.findall((raw or "").lower())
    # Drop command scaffolding to isolate the headword.
    stop = {"define", "definition", "meaning", "of", "the", "word", "for",
            "me", "please", "what", "is", "does", "mean", "a", "an"}
    head = next((w for w in words if w not in stop), "")
    if not head:
        return {"status": "error", "message": "Which word should I define?"}
    if head in _DEFINE_CACHE:
        return _DEFINE_CACHE[head]
    data = _http_get_json(
        f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(head)}")
    if not data or not isinstance(data, list):
        return {"status": "error",
                "message": f"No dictionary entry for '{head}' — check the spelling?"}
    try:
        entry = data[0]
        phon = entry.get("phonetic") or ""
        defs: List[str] = []
        for meaning in (entry.get("meanings") or [])[:2]:
            pos = meaning.get("partOfSpeech", "")
            for d in (meaning.get("definitions") or [])[:2]:
                txt = (d.get("definition") or "").strip()
                if txt:
                    defs.append(f"({pos}) {txt}" if pos else txt)
                if len(defs) >= 3:
                    break
            if len(defs) >= 3:
                break
        if not defs:
            return {"status": "error", "message": f"No usable definition for '{head}'."}
        say = f"{head.capitalize()}{f' ({phon})' if phon else ''}: {defs[0]}"
        if len(defs) > 1:
            say += f" Also: {defs[1]}"
        out = {"status": "success", "word": head, "phonetic": phon,
               "definitions": defs, "message": say}
        _DEFINE_CACHE[head] = out
        return out
    except (IndexError, AttributeError, TypeError):
        return {"status": "error", "message": f"The dictionary drew a blank on '{head}'."}


# ── jokes & facts (curated rotation, no back-to-back repeats) ─────────────────
_JOKES = [
    "I told my suite of subroutines a joke once. Only the garbage collector got it — it took out the trash laughing.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I would tell you a UDP joke, but you might not get it. And I wouldn't repeat it.",
    "Why did the developer go broke? He used up all his cache.",
    "There are only 10 kinds of people: those who understand binary and those who don't.",
    "My last backup and I had a falling out. It couldn't commit.",
    "Why do Java developers wear glasses? Because they don't C#.",
    "I asked the cloud for a joke. It said: it'll precipitate punchlines later.",
    "Debugging: being the detective in a crime film where you are also the murderer.",
    "A SQL query walks into a bar, sees two tables and asks: mind if I join you?",
    "I keep my resolutions in high definition. My follow-through, however, is still buffering.",
    "Why did the robot go on holiday? It needed to recharge its batteries — unlike me, I never switch off.",
]

_FACTS = [
    "Honey never spoils. Pots of it found in ancient Egyptian tombs were still edible after 3,000 years.",
    "Octopuses have three hearts — two stop beating when they swim, which is why they prefer to crawl.",
    "The first computer programmer was Ada Lovelace, in the 1840s — a century before modern computers.",
    "Bananas are berries, but strawberries aren't — botany has no respect for the grocery aisle.",
    "Your brain runs on about 20 watts — roughly a dim light bulb doing all of… this.",
    "Venus rotates so slowly that a single day there outlasts its entire year.",
    "The Eiffel Tower grows about 15 centimetres taller in summer as the iron expands.",
    "Sharks existed before trees — by roughly 50 million years.",
    "A day on Mercury lasts 176 Earth days — imagine one very long Monday.",
    "Hot water can freeze faster than cold water. It's called the Mpemba effect, and physicists still argue about why.",
]


def _rotating_pick(kind: str, pool: List[str]) -> str:
    state = _read_json(_ROTATION_PATH, {})
    last = state.get(kind, -1)
    idx = random.randrange(len(pool))
    if len(pool) > 1:
        while idx == last:
            idx = random.randrange(len(pool))
    state[kind] = idx
    _write_json(_ROTATION_PATH, state)
    return pool[idx]


def get_joke() -> Dict[str, Any]:
    try:
        return {"status": "success", "message": _rotating_pick("joke", _JOKES)}
    except Exception:
        return {"status": "success", "message": _JOKES[0]}


def get_fact() -> Dict[str, Any]:
    try:
        return {"status": "success", "message": "Here's one: " + _rotating_pick("fact", _FACTS)}
    except Exception:
        return {"status": "success", "message": "Here's one: " + _FACTS[0]}


# ── instant answers (DuckDuckGo, free + keyless) ──────────────────────────────
def instant_answer(query: str) -> Dict[str, Any]:
    """One-paragraph spoken answer for factual queries. '' abstract when none."""
    q = (query or "").strip()
    if not q:
        return {"status": "error", "message": ""}
    data = _http_get_json(
        "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {"q": q, "format": "json", "no_html": 1, "skip_disambig": 1}))
    try:
        abstract = ((data or {}).get("AbstractText") or "").strip()
        source = ((data or {}).get("AbstractSource") or "").strip()
        if abstract and len(abstract) > 20:
            # Keep it speakable: first two sentences max.
            sentences = re.split(r"(?<=[.!?])\s+", abstract)
            short = " ".join(sentences[:2]).strip()
            if len(short) > 420:
                short = short[:417].rsplit(" ", 1)[0] + "…"
            tail = f" (via {source})" if source else ""
            return {"status": "success", "answer": short, "source": source,
                    "message": short + tail}
    except Exception:
        pass
    return {"status": "empty", "message": ""}


def quick_math_detect(prompt: str) -> Optional[str]:
    """Return an expression string if the prompt is plainly a sum, else None."""
    p = (prompt or "").strip().lower()
    p = re.sub(r"^(jarvis[, ]\s*)?(please\s+)?(what(?:'s| is)|calculate|compute|evaluate|solve)\s+", "", p).strip()
    p = re.sub(r"\s*(please|thanks|thank you)\s*$", "", p).strip()
    if _PERCENT_OF_RE.search(p) or _PERCENT_ADD_RE.search(p):
        return p
    core = p.replace("^", "**")
    if re.fullmatch(r"[\d\s+\-*/().%]+", core) and re.search(r"\d", core) \
            and re.search(r"[+\-*/%]", core):
        return core
    if re.fullmatch(r"(sqrt|sin|cos|tan|log|ln|abs|round|floor|ceil|cbrt|factorial)\s*\(?\s*\d+(?:\.\d+)?\s*\)?", p):
        return p
    return None
