"""Human reply styler — makes every JARVIS answer sound like a real human butler.

Why this exists:
- Raw tool messages ("Launched notepad", "Increased system volume, sir.")
  are robotic and repeat "sir" on every single line.
- Gemini's `speak` text is usually good already — this module only adds a
  light human polish and NEVER drops factual data (times, temps, paths…).
- Agentic-mode final summaries ("Task complete, sir. 3 of 4 steps…") get
  rewritten into warm, natural closings.

Contract:
- humanize_normal(action_type, gemini_speak, result_message, prompt)
  returns the final chat-ready line.
- humanize_agent(task, completed, total, verification_summary, failed)
  returns the final agentic-mode line.
- humanize_error(kind, detail) returns a calm, plain human error line
  (no jokes on failures — serious moments stay serious).
- All functions never raise and never return "".
"""
from __future__ import annotations

import random
import re
from typing import Optional


def _pick(options: list) -> str:
    try:
        return random.choice(options)
    except Exception:
        return options[0] if options else ""


def _has_sir(text: str) -> bool:
    # English "sir" AND Devanagari "सर" both count — otherwise Hindi replies
    # ending in "…सर।" get a mangled ", sir" stapled on ("…सर।, sir").
    return bool(re.search(r"\bsir\b|सर", (text or ""), re.I))


def _with_sir(text: str, prob: float = 0.35) -> str:
    """Add 'sir' naturally ~prob of the time if not already present."""
    text = (text or "").strip()
    if not text or _has_sir(text):
        return text
    try:
        if random.random() > prob:
            return text
    except Exception:
        return text
    # Prefer trailing address ("…, sir.") — most Jarvis-natural slot.
    if text.endswith((".", "!", "?")):
        return text[:-1] + ", sir" + text[-1]
    return text + ", sir"


def _strip_robotic_prefix(text: str) -> str:
    """Drop leading robotic scaffolding but keep every fact."""
    t = (text or "").strip()
    # Drop things like "RESULT: ..." / "ACTION: ..." if they leak through.
    t = re.sub(r"^(RESULT|ACTION|JARVIS)\s*:\s*", "", t, flags=re.I).strip()
    return t


# ── Per-command human openers / closers (facts are appended, never replaced) ──

_OPENERS = {
    "screenshot": ["Got it — screenshot captured", "Screen grabbed", "Done — I've saved that screenshot"],
    "health": ["Diagnostics complete", "Health check done", "I've given the system a once-over"],
    "stats": ["Here's how the machine looks right now", "Quick look under the hood", "Diagnostics are in"],
    "volume": ["Done", "Sorted", "On it"],
    "media": ["Done", "You got it", "Sorted"],
    "search": ["On it — opening that search now", "Looking that up for you", "Searching now"],
    "folder": ["Folder ready", "Done — folder's in place", "Created"],
    "word_doc": ["Document's ready", "Done — your Word file is written", "Written and saved"],
    "file_write": ["Written and saved", "Done — file's in place", "Saved"],
    "file_read": ["Here it is", "Got it open", "Pulled that up for you"],
    "file_delete": ["Deleted", "Gone — I've removed it", "Taken care of"],
    "image_gen": ["Rendering that for you", "On the canvas now", "Generating your image"],
    "image_save": ["Saved", "Done — image tucked away", "Filed away for you"],
    "open_folder": ["Opening that now", "Here you go", "On your screen now"],
    "launch_app": ["Opening that now", "Firing it up", "Launching it for you"],
    "open_url": ["Opening that for you", "Taking you there now", "On it — opening that page"],
    "mail_read": ["Checking your inbox", "Having a look at your mail", "On your inbox now"],
    "mail_send": ["Sending that now", "Off it goes", "Mail's on its way"],
    "weather": ["Checking the skies", "Having a look outside (meteorologically speaking)", "Consulting the clouds"],
    "datetime": ["Checking the clock", "One glance at the chronometer", "Time check"],
    "battery": ["Checking the power", "Reading the cells", "Power check"],
    "network": ["Scanning the connection", "Checking the lines", "Probing the network"],
    "power": ["Understood", "Right away", "Consider it done"],
    "clipboard": ["Done", "Here you go", "Sorted"],
    "timer": ["Timer's running", "Counting down from now", "Set — I'll keep time"],
    "note": ["Noted", "Written down", "Saved to your notes"],
    "todo": ["Added to your list", "On the list", "Popped that on your todos"],
    "memory": ["Committed to memory", "Locked in", "I'll remember that"],
    "whatsapp": ["Sending that now", "Off it goes", "Relaying your message"],
    "phone": ["On the phone now", "Talking to your handset", "Phone's on it"],
    "code": ["On the code now", "Diving into the source", "Reviewing the codebase"],
    "reminder": ["Locked in", "I'll remind you", "Set — I won't forget"],
    "schedule": ["Scheduled", "Queued up", "Locked into the diary"],
    "calc": ["Crunching done", "Numbers are in", "Worked that out"],
    "convert": ["Converted", "Done — converted", "Here's the conversion"],
    "define": ["Word looked up", "Dictionary says", "Found it"],
    "joke": ["Here's one for you", "Fresh from the humour circuits", "This one always lands"],
    "fact": ["Did you know", "Here's a good one", "Filing this under fascinating"],
    "clean": ["All clean", "Swept and sorted", "Tidied up"],
    "greeting": ["Always a pleasure", "At your service", "Good to hear from you"],
}

_CLOSERS = [
    "",
    "Let me know if you need anything else.",
    "Just say the word if you need more.",
    "Shout if you'd like a hand with anything else.",
]


def _human_wrap(action: str, fact: str, prompt: str = "") -> str:
    fact = _strip_robotic_prefix(fact).strip()
    opener = _pick(_OPENERS.get(action, ["Done"]))
    if not fact:
        return _with_sir(f"{opener}.")
    # If the fact is already a full human sentence (ends with . ! ? and
    # is longer than a stub), keep it and lightly frame it.
    if len(fact) > 60 and fact[-1] in ".!?":
        # Avoid double-framing: if Gemini already wrote personality in,
        # return it as-is (just ensure natural sir usage).
        if _has_sir(fact) or len(fact) > 140:
            return fact
        return _with_sir(f"{fact}")
    # Short stub fact ("Launched notepad") → human sentence.
    combined = f"{opener} — {fact[0].lower() + fact[1:] if fact else ''}"
    if not combined.endswith((".", "!", "?")):
        combined += "."
    # Occasionally append a soft closer (keeps chat alive, human feel).
    try:
        if random.random() < 0.18:
            combined += " " + _pick(_CLOSERS[1:])
    except Exception:
        pass
    return _with_sir(combined)


def humanize_normal(action_type: str = "", gemini_speak: str = "",
                    result_message: str = "", prompt: str = "") -> str:
    """Polish one normal-mode reply. Facts always win over style."""
    try:
        gemini_speak = (gemini_speak or "").strip()
        result_message = (result_message or "").strip()
        prompt = (prompt or "").strip()
        key = (action_type or "").strip().lower()

        # Map raw backend action names to human categories.
        cat = "generic"
        k = key
        if k in ("take_screenshot", "phone_screenshot", "screenshot_ui"):
            cat = "phone" if "phone" in k else "screenshot"
        elif k in ("check_pc_health",):
            cat = "health"
        elif k in ("show_stats",):
            cat = "stats"
        elif k in ("volume_up", "volume_down", "mute_volume"):
            cat = "volume"
        elif k in ("play_pause", "next_track", "prev_track"):
            cat = "media"
        elif k in ("search_web", "browser_search"):
            cat = "search"
        elif k in ("create_folder", "create_folder_verified"):
            cat = "folder"
        elif k in ("create_word_doc", "create_docx", "create_pptx"):
            cat = "word_doc"
        elif k in ("write_file", "write_file_verified"):
            cat = "file_write"
        elif k in ("read_file",):
            cat = "file_read"
        elif k in ("delete_file",):
            cat = "file_delete"
        elif k in ("generate_image",):
            cat = "image_gen"
        elif k in ("save_image",):
            cat = "image_save"
        elif k in ("open_folder",):
            cat = "open_folder"
        elif k in ("open_app", "close_app", "launch_app"):
            cat = "launch_app"
        elif k in ("open_url",):
            cat = "open_url"
        elif k in ("read_email",):
            cat = "mail_read"
        elif k in ("send_email", "gmail_vip"):
            cat = "mail_send"
        elif k in ("weather",):
            cat = "weather"
        elif k in ("datetime_info",):
            cat = "datetime"
        elif k in ("battery",):
            cat = "battery"
        elif k in ("network_info",):
            cat = "network"
        elif k in ("shutdown", "restart", "cancel_shutdown", "sleep", "lock_screen"):
            cat = "power"
        elif k in ("clipboard_read", "clipboard_write"):
            cat = "clipboard"
        elif k in ("set_timer",):
            cat = "timer"
        elif k in ("add_note",):
            cat = "note"
        elif k in ("add_todo",):
            cat = "todo"
        elif k in ("calculate",):
            cat = "calc"
        elif k in ("convert",):
            cat = "convert"
        elif k in ("define",):
            cat = "define"
        elif k in ("joke",):
            cat = "joke"
        elif k in ("fact",):
            cat = "fact"
        elif k in ("empty_recycle", "clean_temp"):
            cat = "clean"
        elif k in ("remember", "clear_history"):
            cat = "memory"
        elif k in ("send_whatsapp", "send_whatsapp_phone", "add_whatsapp_contact"):
            cat = "whatsapp"
        elif k.startswith("phone_"):
            cat = "phone"
        elif k.startswith("code_"):
            cat = "code"
        elif k in ("reminder", "schedule", "snooze", "reschedule"):
            cat = "reminder"

        # Internal-only statuses must NEVER be spoken or blended, no matter
        # which caller passes them ("Memory stored (success)" once leaked
        # into chat here). Drop them as if there were no result at all.
        if (result_message or "").strip().casefold().startswith(
                ("memory stored", "memory store failed", "memory saved",
                 "action: skipping")):
            result_message = ""

        # Performance content (jokes, facts) is a complete act — speak it
        # VERBATIM. Never blend intros, never append openers, never add sir:
        # any of that lands mid-punchline ("…सर।, sir").
        if cat in ("joke", "fact") and result_message:
            return _strip_robotic_prefix(result_message).strip()

        # Full Hindi/Marathi mode: the user speaks Hindi or Marathi, so the
        # WHOLE reply is framed in that language — English openers/leads
        # would read wrong, and an English ", sir" must never land on
        # Devanagari text.
        _HI_DATA_CATS = {"weather", "datetime", "battery", "network", "stats",
                         "clipboard", "mail_read", "mail_send", "file_read",
                         "define", "calc", "convert"}
        try:
            _ulang = _conv_lang(prompt, gemini_speak, result_message)
        except Exception:
            _ulang = "en"
        if _ulang in ("hi", "mr"):
            try:
                if result_message:
                    clean = _strip_robotic_prefix(result_message)
                    if _ulang == "mr":
                        from backend.agent import marathi as _mm
                        mapped = _map_tool_error_mr(clean)
                        if mapped:
                            return mapped
                        if cat in _HI_DATA_CATS:
                            return _mm.mr_lead(cat, clean)
                        return _mm.mr_wrap(cat, clean)
                    from backend.agent import hindi as _hm
                    mapped = _map_tool_error_hi(clean)
                    if mapped:
                        return mapped
                    if cat in _HI_DATA_CATS:
                        return _hm.hi_lead(cat, clean)
                    return _hm.hi_wrap(cat, clean)
                if gemini_speak:
                    return gemini_speak.strip()
                return "झालं।" if _ulang == "mr" else "हो गया।"
            except Exception:
                pass

        # Data-heavy results (weather/time/battery/network/mail/clipboard/
        # stats) already contain the real numbers — frame them, don't rewrite.
        data_cats = {"weather", "datetime", "battery", "network", "stats",
                     "clipboard", "mail_read", "mail_send", "file_read",
                     "define", "calc", "convert"}
        if cat in data_cats and result_message:
            clean = _strip_robotic_prefix(result_message)
            # Keep the data verbatim; add a one-line human lead when the
            # raw message is dry (e.g. starts with "CPU at…", "Clipboard…").
            if len(clean) > 25 and _has_sir(clean):
                return clean
            leads = {
                "weather": _pick(["Here's what the skies say", "Weather's in", "A quick look outside"]),
                "datetime": _pick(["Right now", "Clock says", "Checking —"]),
                "battery": _pick(["Power check", "Here's the battery", "Cells report"]),
                "network": _pick(["Connection report", "Here's the network picture", "Lines are as follows"]),
                "stats": _pick(["Here's the state of the machine", "Quick health snapshot", "Under the hood"]),
                "clipboard": _pick(["Clipboard says", "Here's what's on the clipboard", "Copied text reads"]),
                "mail_read": _pick(["From your inbox", "Here's your mail", "Inbox report"]),
                "mail_send": _pick(["Mail update", "Done", "Sent"]),
                "file_read": _pick(["Here's the file", "Pulled that up", "Contents below"]),
                "define": _pick(["Dictionary says", "Word looked up", "Here's the word"]),
                "calc": _pick(["Crunching done", "The answer is", "Numbers are in"]),
                "convert": _pick(["Converted", "Here's the conversion", "Done"]),
            }
            lead = leads.get(cat, "Here's the result")
            out = f"{lead}: {clean}"
            return _with_sir(out, prob=0.25)

        # Prefer Gemini's personality line when it already carries the fact.
        if gemini_speak and result_message:
            # Gemini spoke before execution (a placeholder like "Fetching
            # weather…") but the tool returned the real data — the data wins.
            if cat in data_cats:
                return humanize_normal(cat, "", result_message, prompt)
            # Otherwise blend: real outcome first, personality preserved.
            if gemini_speak.strip().lower() not in result_message.strip().lower():
                return _with_sir(f"{_strip_robotic_prefix(result_message)} {gemini_speak}".strip())
            return _with_sir(gemini_speak)
        if result_message:
            return _human_wrap(cat, result_message, prompt)
        if gemini_speak:
            return _with_sir(gemini_speak.strip(), prob=0.3)
        return _with_sir("Done — that's taken care of.")
    except Exception:
        # Never break a reply on style.
        for fallback in (gemini_speak, result_message):
            if (fallback or "").strip():
                return fallback.strip()
        return "Done, sir."


def humanize_agent(task: str = "", completed: int = 0, total: int = 0,
                   summary: str = "", failed: bool = False,
                   partial: bool = False) -> str:
    """Warm, human closing line for an agentic run (facts preserved)."""
    try:
        summary = _strip_robotic_prefix((summary or "").strip())
        task_short = (task or "").strip().splitlines()[0][:90].strip()
        if failed and not completed:
            base = "I gave that my best shot, but I couldn't get it over the line."
            if summary:
                return f"{base} {summary}"
            if task_short:
                return f"{base} The '{task_short}' run hit a wall — want me to try a different angle?"
            return base + " Want me to try a different angle?"
        if partial:
            base = _pick([
                "Mostly there — the bulk of it's done",
                "Good progress — the main part landed",
                "Nearly finished",
            ])
            tail = f" ({completed} of {total} steps)" if total else ""
            out = f"{base}{tail}."
            if summary:
                out += f" {summary}"
            elif task_short:
                out += f" The rest of '{task_short}' needs a nudge — say the word and I'll carry on."
            return _with_sir(out, prob=0.3)
        closers = [
            "All wrapped up.",
            "Done and dusted.",
            "That's off your plate.",
            "Consider it handled.",
        ]
        out = _pick(closers)
        if summary:
            # Summary already says what happened — lead with it.
            if len(summary) > 200:
                return _with_sir(summary, prob=0.25)
            return _with_sir(f"{summary} {out}", prob=0.25)
        if total and completed:
            out = f"All {completed} steps landed cleanly — {out.lower()}" if completed == total else f"{completed} of {total} steps are done — {out.lower()}"
        elif task_short:
            out = f"'{task_short}' — {out.lower()}"
        return _with_sir(out, prob=0.35)
    except Exception:
        return (summary or "").strip() or "Done, sir."


def _conv_lang(*texts: str) -> str:
    """Conversation language: 'mr' | 'hi' | 'en'.

    Marathi is checked first — Devanagari is shared, and is_hindi() claims
    all of it. is_marathi() only fires on a Marathi marker win (or clean
    Roman Marathi), so this order never steals Hindi.
    """
    try:
        blob = " ".join(t or "" for t in texts if t)
        if not blob.strip():
            return "en"
        try:
            from backend.agent import marathi as _mm
            if _mm.is_marathi(blob):
                return "mr"
        except Exception:
            pass
        try:
            from backend.agent import hindi as _hm
            if _hm.is_hindi(blob):
                return "hi"
        except Exception:
            pass
    except Exception:
        pass
    return "en"


def _map_tool_error_hi(clean: str) -> Optional[str]:
    """Map known English tool-error strings to Hindi. None when N/A."""
    try:
        from backend.agent import hindi as _hm
        c = (clean or "").casefold()
        if not c:
            return None
        if "only crunch numbers" in c or "couldn't parse that sum" in c:
            return _hm.hi_error("bad_sum")
        if "give me a sum to crunch" in c:
            return _hm.hi_error("empty_calc")
        if "tell me like" in c or "i convert temperature" in c:
            return _hm.hi_error("convert_help")
        if "can't reach the exchange" in c:
            return _hm.hi_error("rates_down")
        if "which word should i define" in c:
            return _hm.hi_error("no_word")
        if "no dictionary entry" in c or "drew a blank" in c:
            return _hm.hi_error("dict_miss")
        if "couldn't retrieve weather" in c:
            return _hm.hi_error("weather_down")
        if "gmail isn't linked" in c or "gmail linked" in c and "isn't" in c:
            return _hm.hi_error("mail_unlinked")
    except Exception:
        pass
    return None


def _map_tool_error_mr(clean: str) -> Optional[str]:
    """Map known English tool-error strings to Marathi. None when N/A."""
    try:
        from backend.agent import marathi as _mm
        c = (clean or "").casefold()
        if not c:
            return None
        if "only crunch numbers" in c or "couldn't parse that sum" in c:
            return _mm.mr_error("bad_sum")
        if "give me a sum to crunch" in c:
            return _mm.mr_error("empty_calc")
        if "tell me like" in c or "i convert temperature" in c:
            return _mm.mr_error("convert_help")
        if "can't reach the exchange" in c:
            return _mm.mr_error("rates_down")
        if "which word should i define" in c:
            return _mm.mr_error("no_word")
        if "no dictionary entry" in c or "drew a blank" in c:
            return _mm.mr_error("dict_miss")
        if "couldn't retrieve weather" in c:
            return _mm.mr_error("weather_down")
        if "gmail isn't linked" in c:
            return _mm.mr_error("mail_unlinked")
    except Exception:
        pass
    return None


def humanize_error(kind: str = "", detail: str = "", prompt: str = "") -> str:
    """Calm, plain failure line. No jokes, no sir-stuffing."""
    try:
        lang = _conv_lang(prompt, detail)
        if lang != "en":
            k = (kind or "").strip().lower()
            mapping = {"offline": "offline", "network": "offline",
                       "timeout": "offline", "auth": "auth",
                       "login": "auth", "permission": "auth",
                       "not_found": "not_found", "missing": "not_found"}
            if lang == "mr":
                try:
                    from backend.agent import marathi as _mm
                    return _mm.mr_error(mapping.get(k, "generic"), detail)
                except Exception:
                    pass
            else:
                try:
                    from backend.agent import hindi as _hm
                    return _hm.hi_error(mapping.get(k, "generic"), detail)
                except Exception:
                    pass
        kind = (kind or "").strip().lower()
        detail = (detail or "").strip()
        # Strip any leaked tracebacks / paths down to one human line.
        detail = re.sub(r"\s+", " ", detail).strip()[:220]
        if kind in ("offline", "network", "timeout"):
            base = "I can't reach the network right now, so I'll work with what's on this machine."
            return f"{base} {detail}".strip() if detail else base
        if kind in ("auth", "login", "permission"):
            base = "That's a permissions wall — I'll need you to approve access before I can go further."
            return f"{base} {detail}".strip() if detail else base
        if kind in ("not_found", "missing"):
            return detail or "I couldn't find that — double-check the name and I'll have another go."
        if detail:
            return detail
        return "Something went wrong on my end — nothing was changed. Want me to try again?"
    except Exception:
        return "Something went wrong — nothing was changed."


def smalltalk(prompt: str = "") -> Optional[str]:
    """Human replies for greetings / pleasantries (normal mode, no tools)."""
    try:
        p = (prompt or "").strip().lower()
        if not p:
            return None
        if re.search(r"\b(good\s*morning|morning)\b", p):
            return _pick([
                "Morning. Systems are warm and I'm all ears — what's first?",
                "Good morning. Coffee's on you, tasks are on me — what are we tackling?",
            ])
        if re.search(r"\b(good\s*evening|evening)\b", p):
            return _pick([
                "Evening. Everything's humming along — what can I do for you?",
                "Good evening. I'm at your disposal — what's on your mind?",
            ])
        if re.search(r"\b(good\s*night|goodnight)\b", p):
            return _pick([
                "Goodnight. I'll keep the lights on and the systems watched.",
                "Rest well — I'll hold the fort.",
            ])
        if re.search(r"^(hi|hey|hello|yo|hiya|namaste)\b", p):
            return _pick([
                "Hello — good to hear from you. What are we working on?",
                "Hey. I'm here and listening — what's the plan?",
                "At your service. What can I take off your plate?",
            ])
        if re.search(r"how are you|how('| i)s it going|how do you feel", p):
            return _pick([
                "Running cool and thinking fast, thanks for asking. How can I help?",
                "All cores green and in good spirits. What do you need?",
            ])
        if re.search(r"kaise ho|कैसे हो|kaisi ho|कैसी हो|aur batao|और बताओ", p):
            return _pick([
                "मैं एकदम बढ़िया हूँ — पूछने के लिए शुक्रिया! बताइए, क्या काम है?",
                "सब सिस्टम हरे हैं और मूड भी अच्छा है। क्या करूँ आपके लिए?",
            ])
        if re.search(r"suprabhat|सुप्रभात|shubh prabhat|शुभ प्रभात", p):
            return _pick([
                "सुप्रभात! सिस्टम गरम हैं और मैं हाज़िर हूँ — आज सबसे पहले क्या करें?",
                "शुभ प्रभात! चाय आपकी, काम मेरे — बताइए क्या करना है?",
            ])
        if re.search(r"shubh ratri|शुभ रात्रि|good night.*hindi|goodnight.*hindi", p):
            return "शुभ रात्रि! बत्तियाँ जलती रहेंगी, सिस्टम पर नज़र रहेगी।"
        if re.search(r"who are you|your name|about yourself", p):
            return "I'm Jarvis — your desktop right hand. I run apps, files, mail, reminders and research, and I talk you through it all as I go."
        # ── Marathi smalltalk (checked before Hindi: shared script) ──
        # Jarvis's own identity ("tumcha naav kay", "तुमचं नाव काय").
        if re.search(r"tumcha|तुमचं|तुमचे|tujha|तुझं|naav kay|नाव काय", p):
            return "माझं नाव J.A.R.V.I.S. आहे — तुमचा नम्र डिजिटल बटलर।"
        # Capabilities ("tu kay karu shaktos", "तू काय करू शकतोस").
        if re.search(r"(tu|तू).{0,20}(kay|काय).{0,20}(karu|करू|shaktos|शकतोस)|what can you do.*marathi", p):
            return ("मी ॲप्स उघडणं, हवामान सांगणं, फाइल्स, मेल आणि रिमाइंडर सांभाळणं, "
                    "हिशोब करणं आणि रिसर्चमध्ये मदत करू शकतो — फक्त सांगून बघा।")
        # How are you ("kase aahat", "कसे आहात").
        if re.search(r"kase aahat|कसे आहात|kashi aahes|कशी आहेस|kasa aahes|कसा आहेस", p):
            return _pick([
                "मी एकदम मजेत आहे — विचारल्याबद्दल धन्यवाद! सांगा, काय काम आहे?",
                "सगळे सिस्टीम हिरवे आहेत आणि मूडही छान आहे। काय करू तुमच्यासाठी?",
            ])
        if re.search(r"namaskar|नमस्कार", p):
            return _pick([
                "नमस्कार! मी हजर आहे — सांगा, काय काम आहे?",
                "नमस्कार! सगळे सिस्टीम तयार आहेत — काय करू तुमच्यासाठी?",
            ])
        # Jarvis's own identity in Hindi ("tumhara naam kya hai").
        if re.search(r"tumhara|tumharaa|aapka|आपका|तुम्हारा|तुम्हारा नाम|naam kya|नाम क्या", p):
            return "मेरा नाम J.A.R.V.I.S. है — आपका विनम्र डिजिटल बटलर।"
        # Capabilities in Hindi ("tum kya kya kar sakte ho").
        if re.search(r"(tum|आप|तुम).{0,20}(kya|क्या).{0,20}(kar sakte|कर सकते)|what can you do", p):
            return ("मैं ऐप्स खोलने, मौसम बताने, फाइलें, मेल और रिमाइंडर संभालने, "
                    "हिसाब-किताब करने और रिसर्च में मदद कर सकता हूँ — बस कहकर देखिए।")
        if re.search(r"namaste|नमस्ते", p):
            return _pick([
                "नमस्ते! मैं हाज़िर हूँ — बताइए, क्या काम है?",
                "नमस्ते! सब सिस्टम तैयार हैं — क्या करूँ आपके लिए?",
            ])
        if re.search(r"thank|thanks|shukriya|dhanyavad|धन्यवाद|शुक्रिया", p):
            try:
                from backend.agent import marathi as _mm
                if _mm.is_marathi(prompt):
                    return "काही हरकत नाही — हेच तर माझं काम आहे!"
            except Exception:
                pass
            return _pick([
                "Always a pleasure.",
                "Anytime — that's what I'm here for.",
                "Happy to help.",
                "कोई बात नहीं — यही तो मेरा काम है!",
            ])
        if re.search(r"\b(bye|goodbye|see you|alvida|अलविदा)\b", p):
            return _pick([
                "Standing by whenever you need me.",
                "I'll be here — just say the word.",
            ])
        return None
    except Exception:
        return None
