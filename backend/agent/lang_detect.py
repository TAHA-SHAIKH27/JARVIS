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

# SAPI LCIDs for voice matching.
SAPI_LCID = {"en": (0x409,), "hi": (0x439,), "mr": (0x44E,),
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


def _script_lang(text: str) -> Optional[str]:
    if _DEVANAGARI_RE.search(text or ""):
        mr = sum(1 for m in _MR_MARKERS if m in text)
        hi = sum(1 for m in _HI_MARKERS if m in text)
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


def select_voice_for_lang(voices: List[Dict[str, Any]], lang: str) -> Optional[Dict[str, Any]]:
    """Pick the best installed voice for lang from a SAPI-style voice list.

    Each voice: {"id", "name", "language"}. Prefers LCID match, then a name
    containing the language name. Returns None when nothing matches (caller
    keeps the current voice). Never raises.
    """
    try:
        if lang not in LANGS:
            lang = "en"
        names = {"en": ("english",), "hi": ("hindi",), "mr": ("marathi",),
                 "ur": ("urdu",), "fr": ("french", "français", "francais"),
                 "es": ("spanish", "español", "espanol")}
        lcids = set(SAPI_LCID.get(lang, ()))
        for voice in voices or []:
            if not isinstance(voice, dict):
                continue
            if _lang_attr_to_lcid(voice.get("language")) in lcids:
                return voice
        for voice in voices or []:
            if not isinstance(voice, dict):
                continue
            blob = f"{voice.get('name', '')} {voice.get('id', '')}".lower()
            if any(n in blob for n in names.get(lang, ())):
                return voice
    except Exception:
        pass
    return None
