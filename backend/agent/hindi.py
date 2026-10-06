"""hindi.py — full Hindi conversation support for J.A.R.V.I.S.

One central place for everything Hindi so the whole loop (understand →
remember → remind → reply → speak) works in Hindi, not just jokes:

  is_hindi(text)          True for Devanagari OR clear Hinglish markers
  say(prompt, en, hi)     pick the Hindi variant when the prompt is Hindi
  human wrappers          Hindi openers / leads / errors / confirmations
  describe_when_hindi     "aaj shaam 6 baje" style due-time phrasing

Tone: warm, respectful, lightly witty — same butler, Hindi voice. The
address word is सर, used sparingly inside templates (never stapled on
afterwards — that produced the "…सर।, sir" bug).
"""
from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Optional

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Unambiguous Roman-Hindi markers (word-boundary matched). Kept tight so
# English sentences never trip it ("me", "na", "to" deliberately excluded).
# NOTE: deliberately excludes Roman words that collide with English names
# or nouns ("Roz", "Har", "koi" fish, "band", "din" noise, pirate "ho").
# Scheduler time-scoring (below) uses its own stricter multi-marker rule.
_HINGLISH_MARKERS = frozenset({
    "kya", "kaise", "kaisi", "kyun", "kyon", "kahan", "kaha", "kab", "kaun",
    "kitna", "kitni", "kaunsa", "kaunsi", "mera", "meri", "mere", "tumhara",
    "tumhari", "tumhe", "tumko", "mujhe", "mujhko", "aapka", "aapki",
    "aapko", "mausam", "batao", "bataye", "sunao", "suna", "yaad",
    "rozana", "baje", "bajje", "ghante", "ghanta", "namaste", "dhanyavad",
    "shukriya", "kaam", "samajh", "raha", "rahi", "rahe", "hai", "hain",
    "karo", "kijiye", "lijiye", "dedo", "lagao", "chalao", "kholo",
    "badhai", "achha", "accha", "bahut", "thoda", "nahi", "subah",
    "savere", "dopahar", "shaam", "raat", "aaj", "kal", "parson",
    "hafte", "chutkula", "tathya", "hindi", "hinglish", "hindustani",
    "ganit", "hisab", "hishob", "uttar", "sodav",
})


def is_hindi(text: str) -> bool:
    """True when the text is Hindi (Devanagari) or clearly Hinglish."""
    try:
        t = text or ""
        if not t:
            return False
        if _DEVANAGARI_RE.search(t):
            return True
        words = set(re.findall(r"[a-z]+", t.casefold()))
        return len(words & _HINGLISH_MARKERS) >= 1 and not re.search(
            r"\b(the|and|please|hello|thanks|morning|evening|weather|reminder|"
            r"timer|email|whatsapp|computer|system|file|folder|search)\b",
            t.casefold())
    except Exception:
        return False


def say(prompt: str, en: str, hi: str) -> str:
    """Pick the Hindi variant when the user's prompt is Hindi."""
    try:
        return hi if is_hindi(prompt) else en
    except Exception:
        return en


def _pick(options: list) -> str:
    try:
        return random.choice(options)
    except Exception:
        return options[0] if options else ""


# ── Hindi openers per command category ────────────────────────────────────────
_HI_OPENERS = {
    "screenshot": ["हो गया — स्क्रीनशॉट ले लिया", "स्क्रीन कैद कर ली"],
    "health": ["जाँच पूरी हुई", "सिस्टम देख लिया"],
    "stats": ["मशीन का हाल ये रहा", "अंदर झाँककर आया"],
    "volume": ["हो गया", "ठीक है"],
    "media": ["हो गया", "जैसी आज्ञा"],
    "search": ["ढूँढ रहा हूँ", "खोज शुरू"],
    "folder": ["फोल्डर तैयार", "बना दिया"],
    "word_doc": ["दस्तावेज़ तैयार", "लिख दिया"],
    "file_write": ["लिखकर सहेज दिया", "हो गया"],
    "file_read": ["ये रहा", "खोल दिया"],
    "file_delete": ["हटा दिया", "साफ़"],
    "image_gen": ["तस्वीर बना रहा हूँ", "कैनवास पर हूँ"],
    "open_folder": ["खोल रहा हूँ", "ये लीजिए"],
    "launch_app": ["खोल रहा हूँ", "शुरू करता हूँ"],
    "open_url": ["खोल रहा हूँ", "ले चलता हूँ"],
    "mail_read": ["इनबॉक्स देख रहा हूँ", "मेल पढ़ता हूँ"],
    "mail_send": ["भेज रहा हूँ", "रवाना"],
    "weather": ["आसमान देखकर आया", "मौसम की खबर"],
    "datetime": ["घड़ी देखी", "समय देखता हूँ"],
    "battery": ["बैटरी देखी", "पावर नापी"],
    "network": ["कनेक्शन जाँचा", "लाइनें देखीं"],
    "power": ["समझ गया", "अभी करता हूँ"],
    "clipboard": ["हो गया", "ये लीजिए"],
    "timer": ["टाइमर चल पड़ा", "गिनती शुरू"],
    "note": ["लिख लिया", "नोट कर लिया"],
    "todo": ["सूची में डाल दिया", "जोड़ दिया"],
    "memory": ["याद रखूँगा", "दिमाग़ में बैठ गया"],
    "calc": ["हिसाब हो गया", "गिनती पूरी"],
    "convert": ["बदल दिया", "हो गया"],
    "define": ["शब्दकोश बोला", "मतलब मिला"],
    "clean": ["साफ़-सुथरा", "चमका दिया"],
    "reminder": ["पक्का", "याद दिलाऊँगा"],
    "schedule": ["दर्ज़ हो गया", "डायरी में लिखा"],
}

_HI_LEADS = {
    "weather": ["मौसम का हाल", "आसमान की खबर"],
    "datetime": ["अभी", "घड़ी बोली"],
    "battery": ["बैटरी बोली", "पावर का हाल"],
    "network": ["कनेक्शन रिपोर्ट", "लाइन का हाल"],
    "stats": ["मशीन की नब्ज़", "अंदर का हाल"],
    "clipboard": ["क्लिपबोर्ड बोला", "नक़ल में ये है"],
    "mail_read": ["इनबॉक्स से", "आपकी डाक"],
    "mail_send": ["मेल का हाल", "भेज दिया"],
    "file_read": ["फाइल हाज़िर", "ये रहे अंदर के हाल"],
    "define": ["शब्दकोश बोला", "मतलब ये रहा"],
    "calc": ["हिसाब बोला", "जवाब हाज़िर"],
    "convert": ["बदलकर", "हिसाब ये रहा"],
}

_HI_CLOSERS = [
    "",
    "और कुछ चाहिए तो बस कहिएगा।",
    "कुछ और काम हो तो हाज़िर हूँ।",
]


def hi_wrap(action: str, fact: str) -> str:
    """Frame a Hindi fact naturally. Facts stay verbatim; no sir-stapling."""
    fact = (fact or "").strip()
    opener = _pick(_HI_OPENERS.get(action, ["हो गया"]))
    if not fact:
        return opener + "।"
    if len(fact) > 140 or fact[-1] in ".!?।":
        return fact
    out = f"{opener} — {fact}"
    if not out.endswith((".", "!", "?", "।")):
        out += "।"
    try:
        if random.random() < 0.15:
            out += " " + _pick(_HI_CLOSERS[1:])
    except Exception:
        pass
    return out.strip()


def hi_lead(cat: str, fact: str) -> str:
    """One-line Hindi lead + verbatim fact (data-heavy results)."""
    fact = (fact or "").strip()
    if not fact:
        return _pick(_HI_OPENERS.get(cat, ["हो गया"])) + "।"
    if len(fact) > 140:
        return fact
    return f"{_pick(_HI_LEADS.get(cat, ['ये रहा']))}: {fact}"


# ── Hindi errors (calm, plain — no jokes on failures) ─────────────────────────
_HI_ERRORS = {
    "generic": "कुछ गड़बड़ हुई — कुछ बदला नहीं है। फिर से कोशिश करूँ?",
    "offline": "नेटवर्क नहीं मिल रहा — जो इस मशीन पर है, उसी से काम चलाऊँगा।",
    "auth": "अनुमति अटकी है — आगे बढ़ने से पहले आपको मंज़ूरी देनी होगी।",
    "not_found": "वो मिला नहीं — नाम दोबारा देखकर बताइए, फिर कोशिश करता हूँ।",
    "empty_calc": "कोई हिसाब दीजिए — जैसे 18% of 4500।",
    "bad_sum": "ये हिसाब समझ न आया — जैसे (12 + 8) * 3 करके देखिए।",
    "no_word": "कौन-सा शब्द समझाऊँ?",
    "dict_miss": "इस शब्द की प्रविष्टि न मिली — वर्तनी देख लीजिए?",
    "convert_help": "ऐसे बताइए: 32C to F, 5 km to miles, या 100 USD to INR।",
    "rates_down": "मुद्रा दर सेवा नहीं मिल रही — कनेक्शन देखकर फिर कोशिश कीजिए।",
    "weather_down": "मौसम न मिल सका — शहर का नाम या कनेक्शन देख लीजिए।",
    "mail_unlinked": "Gmail जुड़ा नहीं है — Settings में जोड़िए, फिर इनबॉक्स सीधे पढ़ूँगा।",
}


def hi_error(kind: str = "", detail: str = "") -> str:
    try:
        base = _HI_ERRORS.get((kind or "").strip().lower(), _HI_ERRORS["generic"])
        detail = re.sub(r"\s+", " ", detail or "").strip()[:200]
        return f"{base} {detail}".strip() if detail else base
    except Exception:
        return _HI_ERRORS["generic"]


# ── Hindi confirmations ───────────────────────────────────────────────────────
def hi_memory_saved(memory_text: str) -> str:
    t = (memory_text or "").strip()
    return f"समझ गया — याद रखूँगा: {t}" if t else "समझ गया — याद रखूँगा।"


def hi_name_answer(name: str) -> str:
    return f"आपका नाम {name} है — अच्छी तरह याद है मुझे।"


def hi_city_answer(city: str) -> str:
    return f"आप {city} में रहते हैं — वहीं घर है आपका।"


def hi_identity_answer() -> str:
    return "मेरा नाम J.A.R.V.I.S. है — आपका विनम्र डिजिटल बटलर।"


# ── Hindi due-time phrasing ("aaj shaam 6 baje") ──────────────────────────────
_HI_DAYPART = (
    (5, 12, "सुबह"), (12, 17, "दोपहर"), (17, 21, "शाम"), (21, 24, "रात"), (0, 5, "रात"),
)


def _hi_daypart(hour: int) -> str:
    for lo, hi, name in _HI_DAYPART:
        if lo <= hour < hi:
            return name
    return ""


def _hi_clock(when: datetime) -> str:
    h24, m = when.hour, when.minute
    h12 = h24 % 12 or 12
    t = f"{h12}:{m:02d} बजे" if m else f"{h12} बजे"
    part = _hi_daypart(h24)
    return f"{part} {t}" if part else t


def describe_when_hindi(when: datetime) -> str:
    """Human-friendly Hindi: 'aaj shaam 6 baje', 'kal subah 9 baje'."""
    try:
        now = datetime.now().astimezone()
        try:
            local = when.astimezone(now.tzinfo)
        except Exception:
            local = when
        clock = _hi_clock(local)
        if local.date() == now.date():
            return f"आज {clock}"
        if local.date() == (now + timedelta(days=1)).date():
            return f"कल {clock}"
        days = ("सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार")
        return f"{days[local.weekday()]} {clock}"
    except Exception:
        return ""
