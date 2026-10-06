"""marathi.py — full Marathi conversation support for J.A.R.V.I.S.

Mirrors hindi.py: one central place so Marathi works end-to-end
(understand → remember → remind → reply → speak), never half-framed.

  is_marathi(text)        Devanagari-with-Marathi-win OR Roman markers
  say(prompt, en, mr)     pick the Marathi variant for Marathi prompts
  mr_wrap / mr_lead       Marathi openers / leads (सर used sparingly)
  mr_error                calm Marathi failures
  confirmations           memory / name / city / identity answers
  describe_when_marathi   "आज संध्याकाळी 6 वाजता" style due times

Devanagari is shared with Hindi, so script alone never decides: Marathi
markers must strictly outnumber Hindi ones (see lang_detect.prefer_marathi).
Roman-Marathi markers are kept collision-free ("Mala"/"Kara" as names are
deliberately excluded).
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Collision-free Roman-Marathi markers (no English-name collisions).
_ROMAN_MR_MARKERS = frozenset({
    "maza", "mazi", "maze", "majha", "majhi", "tula", "tumhi", "aamhi",
    "kasa", "kashi", "kuthe", "aahe", "ahe", "nako", "hoy",
    "pahije", "sanga", "sang", "kartoy", "kartos", "karto",
    "karte", "kela", "keli", "udya", "parva", "aaj", "sakali",
    "dupari", "sandhyakali", "ratri", "vajta", "vajle", "aathvan",
    "darroj", "havaman", "namaskar", "dhanyavad", "krupaya", "thoda",
    "milat", "miltat",
})


def is_marathi(text: str) -> bool:
    """True for Marathi Devanagari (marker win) or clear Roman Marathi."""
    try:
        t = text or ""
        if not t:
            return False
        if _DEVANAGARI_RE.search(t):
            try:
                from backend.agent.lang_detect import prefer_marathi
                return prefer_marathi(t)
            except Exception:
                return False
        words = set(re.findall(r"[a-z]+", t.casefold()))
        return len(words & _ROMAN_MR_MARKERS) >= 1 and not re.search(
            r"\b(the|and|please|hello|thanks|morning|evening|weather|reminder|"
            r"timer|email|whatsapp|computer|system|file|folder|search|joke|fact)\b",
            t.casefold())
    except Exception:
        return False


def say(prompt: str, en: str, mr: str) -> str:
    """Pick the Marathi variant when the user's prompt is Marathi."""
    try:
        return mr if is_marathi(prompt) else en
    except Exception:
        return en


def _pick(options: list) -> str:
    try:
        return random.choice(options)
    except Exception:
        return options[0] if options else ""


# ── Marathi openers per command category ──────────────────────────────────────
_MR_OPENERS = {
    "screenshot": ["झालं — स्क्रीनशॉट घेतला", "स्क्रीन कैद केली"],
    "health": ["तपासणी पूर्ण", "सिस्टीम बघितलं"],
    "stats": ["मशीनची नाडी ही राहिली", "आत डोकावून आलो"],
    "volume": ["झालं", "ठीक आहे"],
    "media": ["झालं", "जशी आज्ञा"],
    "search": ["शोधतोय", "शोध सुरू"],
    "folder": ["फोल्डर तयार", "बनवलं"],
    "word_doc": ["दस्तऐवज तयार", "लिहिलं"],
    "file_write": ["लिहून जतन केलं", "झालं"],
    "file_read": ["हे घ्या", "उघडलं"],
    "file_delete": ["काढून टाकलं", "साफ"],
    "image_gen": ["चित्र काढतोय", "कॅनव्हासवर आहे"],
    "open_folder": ["उघडतोय", "हे घ्या"],
    "launch_app": ["उघडतोय", "सुरू करतोय"],
    "open_url": ["उघडतोय", "घेऊन जातोय"],
    "mail_read": ["इनबॉक्स बघतोय", "मेल वाचतोय"],
    "mail_send": ["पाठवतोय", "रवाना"],
    "weather": ["आभाळ बघून आलो", "हवामानाची खबर"],
    "datetime": ["घड्याळ बघितलं", "वेळ बघतोय"],
    "battery": ["बॅटरी बघितली", "पॉवर मोजली"],
    "network": ["कनेक्शन तपासलं", "लाइनी बघितल्या"],
    "power": ["समजलं", "लगेच करतोय"],
    "clipboard": ["झालं", "हे घ्या"],
    "timer": ["टायमर सुरू झाला", "मोजणी सुरू"],
    "note": ["लिहून घेतलं", "नोंद केली"],
    "todo": ["यादीत टाकलं", "जोडलं"],
    "memory": ["लक्षात ठेवीन", "डोक्यात बसलं"],
    "calc": ["हिशोब झाला", "गणित पूर्ण"],
    "convert": ["बदललं", "झालं"],
    "define": ["शब्दकोश बोलला", "अर्थ सापडला"],
    "clean": ["सगळं स्वच्छ", "चकाचक केलं"],
    "reminder": ["नक्की", "आठवण करून देईन"],
    "schedule": ["नोंदवलं", "डायरीत लिहिलं"],
}

_MR_LEADS = {
    "weather": ["हवामानाचा अंदाज", "आभाळाची खबर"],
    "datetime": ["आत्ता", "घड्याळ बोललं"],
    "battery": ["बॅटरी बोलली", "पॉवरचा हाल"],
    "network": ["कनेक्शन रिपोर्ट", "लाइनचा हाल"],
    "stats": ["मशीनची नाडी", "आतला हाल"],
    "clipboard": ["क्लिपबोर्ड बोलला", "नकलेत हे आहे"],
    "mail_read": ["इनबॉक्समधून", "तुमची डाक"],
    "mail_send": ["मेलचा हाल", "पाठवलं"],
    "file_read": ["फाइल हजर", "आतला मजकूर"],
    "define": ["शब्दकोश बोलला", "अर्थ हा राहिला"],
    "calc": ["हिशोब बोलला", "उत्तर हजर"],
    "convert": ["बदलून", "हिशोब हा राहिला"],
}

_MR_CLOSERS = [
    "",
    "आणखी काही हवं असेल तर फक्त सांगा।",
    "काही काम असेल तर हजर आहे।",
]


def mr_wrap(action: str, fact: str) -> str:
    """Frame a Marathi fact naturally. Facts stay verbatim; no sir-stapling."""
    fact = (fact or "").strip()
    opener = _pick(_MR_OPENERS.get(action, ["झालं"]))
    if not fact:
        return opener + "।"
    if len(fact) > 140 or fact[-1] in ".!?।":
        return fact
    out = f"{opener} — {fact}"
    if not out.endswith((".", "!", "?", "।")):
        out += "।"
    try:
        if random.random() < 0.15:
            out += " " + _pick(_MR_CLOSERS[1:])
    except Exception:
        pass
    return out.strip()


def mr_lead(cat: str, fact: str) -> str:
    """One-line Marathi lead + verbatim fact (data-heavy results)."""
    fact = (fact or "").strip()
    if not fact:
        return _pick(_MR_OPENERS.get(cat, ["झालं"])) + "।"
    if len(fact) > 140:
        return fact
    return f"{_pick(_MR_LEADS.get(cat, ['हे घ्या']))}: {fact}"


# ── Marathi errors (calm, plain — no jokes on failures) ──────────────────────
_MR_ERRORS = {
    "generic": "काहीतरी बिघडलं — काहीही बदललेलं नाही. पुन्हा प्रयत्न करू?",
    "offline": "नेटवर्क सापडत नाही — या मशीनवर जे आहे त्यातूनच काम भागवतो.",
    "auth": "परवानगी अडकली आहे — पुढे जाण्यापूर्वी तुम्हाला मंजुरी द्यावी लागेल.",
    "not_found": "ते सापडलं नाही — नाव पुन्हा बघून सांगा, मग प्रयत्न करतो.",
    "empty_calc": "एखादा हिशोब द्या — जसं 18% of 4500.",
    "bad_sum": "हा हिशोब समजला नाही — जसं (12 + 8) * 3 करून बघा.",
    "no_word": "कोणता शब्द समजावू?",
    "dict_miss": "या शब्दाची नोंद सापडली नाही — स्पेलिंग बघा?",
    "convert_help": "असं सांगा: 32C to F, 5 km to miles, किंवा 100 USD to INR.",
    "rates_down": "चलन दर सेवा मिळत नाही — कनेक्शन बघून पुन्हा प्रयत्न करा.",
    "weather_down": "हवामान मिळालं नाही — शहराचं नाव किंवा कनेक्शन बघा.",
    "mail_unlinked": "Gmail जोडलेलं नाही — Settings मध्ये जोडा, मग इनबॉक्स थेट वाचतो.",
}


def mr_error(kind: str = "", detail: str = "") -> str:
    try:
        base = _MR_ERRORS.get((kind or "").strip().lower(), _MR_ERRORS["generic"])
        detail = re.sub(r"\s+", " ", detail or "").strip()[:200]
        return f"{base} {detail}".strip() if detail else base
    except Exception:
        return _MR_ERRORS["generic"]


# ── Marathi confirmations ─────────────────────────────────────────────────────
def mr_memory_saved(memory_text: str) -> str:
    t = (memory_text or "").strip()
    return f"समजलं — लक्षात ठेवीन: {t}" if t else "समजलं — लक्षात ठेवीन।"


def mr_name_answer(name: str) -> str:
    return f"तुमचं नाव {name} आहे — चांगलंच लक्षात आहे माझ्या।"


def mr_city_answer(city: str) -> str:
    return f"तुम्ही {city} मध्ये राहता — तिथंच घर आहे तुमचं।"


def mr_identity_answer() -> str:
    return "माझं नाव J.A.R.V.I.S. आहे — तुमचा नम्र डिजिटल बटलर।"


# ── Marathi due-time phrasing ("आज संध्याकाळी 6 वाजता") ───────────────────────
_MR_DAYPART = (
    (5, 12, "सकाळी"), (12, 17, "दुपारी"), (17, 21, "संध्याकाळी"),
    (21, 24, "रात्री"), (0, 5, "रात्री"),
)


def _mr_daypart(hour: int) -> str:
    for lo, hi, name in _MR_DAYPART:
        if lo <= hour < hi:
            return name
    return ""


def _mr_clock(when: datetime) -> str:
    h24, m = when.hour, when.minute
    h12 = h24 % 12 or 12
    t = f"{h12}:{m:02d} वाजता" if m else f"{h12} वाजता"
    part = _mr_daypart(h24)
    return f"{part} {t}" if part else t


def describe_when_marathi(when: datetime) -> str:
    """Human-friendly Marathi: 'आज संध्याकाळी 6 वाजता', 'उद्या सकाळी 9 वाजता'."""
    try:
        now = datetime.now().astimezone()
        try:
            local = when.astimezone(now.tzinfo)
        except Exception:
            local = when
        clock = _mr_clock(local)
        if local.date() == now.date():
            return f"आज {clock}"
        if local.date() == (now + timedelta(days=1)).date():
            return f"उद्या {clock}"
        days = ("सोमवारी", "मंगळवारी", "बुधवारी", "गुरुवारी",
                "शुक्रवारी", "शनिवारी", "रविवारी")
        return f"{days[local.weekday()]} {clock}"
    except Exception:
        return ""
