"""lang_detect.py — reply-language detection for JARVIS speech.

Supports Hindi (hi), Marathi (mr), Urdu (ur), English (en), French (fr),
Spanish (es). Used to pick a matching TTS voice so JARVIS *speaks* the
reply in the language it is written in.

Rules (cheap, offline, deterministic):
- Explicit request in the user's prompt wins ("in hindi", "hindi me",
  "marathi madhe", "in urdu", "en français", "in spanish", ...).
- Devanagari script → hi, or mr when Marathi markers outnumber Hindi ones
  (both share the script; heuristic, documented).
- Perso-Arabic script → ur.
- ñ/¿/¡ → es; ç/œ/æ (and friends) → fr; otherwise Latin → en.

SAPI voice matching is a pure helper over [{id, name, language}] so it is
unit-testable without Windows speech installed. Language attributes are
compared as LCIDs (hex or decimal) with a name fallback.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

LANGS = ("hi", "mr", "ur", "en", "fr", "es")

# SAPI LCIDs for voice matching (en covers US + Britain so Daniel counts).
SAPI_LCID = {"en": (0x409, 0x809), "hi": (0x439,), "mr": (0x44E,),
             "ur": (0x448,), "fr": (0x40C, 0xC0C), "es": (0x40A, 0xC0A)}

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

_MR_MARKERS = ("आहे", "नाही", "नको", "मला", "तुला", "तुम्ही", "आम्ही",
               "कसे", "कशी", "कुठे", "माझा", "माझं", "माझी", "तुझा",
               "तुझी", "होय", "काय ", " काय", "पाहिजे", "करतो", "करते")
_HI_MARKERS = ("है", "हैं", "नहीं", "मुझे", "तुम्हें", "तुम्हारा",
               "कैसे", "कैसी", "कहाँ", "क्या", "मेरा", "मेरी", "तेरा",
               "आपका", "आपकी", "होगा", "होगी", "रहा", "रही", "वाला")

# (lang, prompt patterns) — explicit user request always wins.
_HINT_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("hi", ("in hindi", "hindi me", "hindi mein", "हिंदी में", "हिन्दी में",
            "hindi joke", "hindi story", "in the hindi")),
    ("mr", ("in marathi", "marathi me", "marathi madhe", "marathi madhye",
            "मराठीत", "मराठी मध्ये", "marathi joke", "marathi story")),
    ("ur", ("in urdu", "urdu me", "urdu mein", "اردو میں", "urdu joke",
            "urdu story")),
    ("fr", ("in french", "en français", "en francais", "french joke",
            "french story", "parle français", "parle francais")),
    ("es", ("in spanish", "en español", "en espanol", "spanish joke",
            "spanish story", "habla español", "habla espanol")),
    ("en", ("in english", "english me", "english joke")),
)


def _hint_lang(hint: str) -> Optional[str]:
    lowered = (hint or "").lower()
    for lang, patterns in _HINT_PATTERNS:
        if any(p in lowered for p in patterns):
            return lang
    return None


def hi_mr_counts(text: str) -> Tuple[int, int]:
    """(hindi_markers, marathi_markers) in Devanagari text. Never raises."""
    try:
        t = text or ""
        return (sum(1 for m in _HI_MARKERS if m in t),
                sum(1 for m in _MR_MARKERS if m in t))
    except Exception:
        return (0, 0)


def prefer_marathi(text: str) -> bool:
    """True when Marathi markers strictly outnumber Hindi ones.

    Used to pick Marathi (not Hindi) framing for Devanagari text — the
    two share a script, so a bare script check can't tell them apart.
    """
    try:
        if not _DEVANAGARI_RE.search(text or ""):
            return False
        hi, mr = hi_mr_counts(text)
        return mr > hi
    except Exception:
        return False


def _script_lang(text: str) -> Optional[str]:
    if _DEVANAGARI_RE.search(text or ""):
        hi, mr = hi_mr_counts(text)
        return "mr" if mr > hi else "hi"
    if _ARABIC_RE.search(text or ""):
        return "ur"
    return None


def _accent_lang(text: str) -> Optional[str]:
    if re.search(r"[ñ¿¡]", text or ""):
        return "es"
    if re.search(r"[çœæàâêëîïôûù]", text or ""):
        return "fr"
    return None


def detect_lang(text: str, hint: str = "") -> str:
    """Detect the reply language. Returns a code from LANGS, never raises."""
    try:
        hinted = _hint_lang(hint)
        if hinted:
            return hinted
        script = _script_lang(text)
        if script:
            return script
        accent = _accent_lang(text)
        if accent:
            return accent
    except Exception:
        pass
    return "en"


def _lang_attr_to_lcid(value: Any) -> Optional[int]:
    """SAPI Language attributes are hex LCID strings ("409" = 0x409)."""
    try:
        s = str(value).strip().lower().rstrip("h")
        if s.startswith("0x"):
            return int(s, 16)
        try:
            return int(s, 16)
        except ValueError:
            return int(s)
    except (TypeError, ValueError):
        return None


def _voice_name_tokens(voice: Dict[str, Any]) -> List[str]:
    try:
        blob = f"{voice.get('name', '')} {voice.get('id', '')}".lower()
        return re.split(r"[^a-zàâêëîïôûùçœæñ]+", blob)
    except Exception:
        return []


# JARVIS is male: within one language, a male voice always wins over a
# female one, and an androgynous/unknown voice beats a female one. Tokens
# are whole-word so "man" never matches "Samantha".
_MALE_TOKENS = frozenset({
    "male", "man", "david", "mark", "daniel", "james", "george", "guy",
    "madhur", "hemant", "pablo", "jorge", "diego", "carlos", "paul",
    "thomas", "alexander", "fred", "arthur", "oscar",
})
_FEMALE_TOKENS = frozenset({
    "female", "woman", "zira", "samantha", "aria", "jenny", "swara",
    "kalpana", "helena", "laura", "monica", "hortense", "julie", "hazel",
    "sabina", "heera", "kanya", "veena", "lekha", "susan", "karen",
})


def _voice_masculinity_rank(voice: Dict[str, Any]) -> int:
    """0 = male, 1 = unknown, 2 = female. Explicit SAPI Gender wins first."""
    try:
        gender = str(voice.get("gender", "") or "").strip().lower()
        if gender == "male":
            return 0
        if gender == "female":
            return 2
    except Exception:
        pass
    tokens = set(_voice_name_tokens(voice))
    male = bool(tokens & _MALE_TOKENS)
    female = bool(tokens & _FEMALE_TOKENS)
    if male and not female:
        return 0
    if female and not male:
        return 2
    return 1


def _prefer_male(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Most masculine candidate first (stable — unknowns keep order)."""
    if not candidates:
        return None
    return sorted(candidates, key=_voice_masculinity_rank)[0]


def select_voice_for_lang(voices: List[Dict[str, Any]], lang: str) -> Optional[Dict[str, Any]]:
    """Pick the best installed voice for lang from a SAPI-style voice list.

    Each voice: {"id", "name", "language"}. Prefers LCID match, then a name
    containing the language name. Within one language JARVIS is male, so a
    male voice always beats a female one. Returns None when nothing matches
    (caller keeps the current voice). Never raises.
    """
    try:
        if lang not in LANGS:
            lang = "en"
        names = {"en": ("english",), "hi": ("hindi",), "mr": ("marathi",),
                 "ur": ("urdu",), "fr": ("french", "français", "francais"),
                 "es": ("spanish", "español", "espanol")}
        lcids = set(SAPI_LCID.get(lang, ()))
        lcid_hits = [
            voice for voice in voices or []
            if isinstance(voice, dict)
            and _lang_attr_to_lcid(voice.get("language")) in lcids
        ]
        if lcid_hits:
            return _prefer_male(lcid_hits)
        name_hits = []
        for voice in voices or []:
            if not isinstance(voice, dict):
                continue
            blob = f"{voice.get('name', '')} {voice.get('id', '')}".lower()
            if any(n in blob for n in names.get(lang, ())):
                name_hits.append(voice)
        if name_hits:
            return _prefer_male(name_hits)
    except Exception:
        pass
    return None
