"""Pre-plan clarification: ask when the prompt is genuinely unclear.

Like a good assistant (Claude/Gemini/ChatGPT), the agent asks ONE focused
question instead of guessing — but only when it is truly blocked. Valid,
plannable tasks must NEVER be interrogated: anything with a URL, a quoted
string, a number to crunch, a known app, or a research topic + artifact
passes straight through.

`needs_clarification(task)` returns {"question", "options", "hint"} or None.
"""
import re
from typing import Any, Dict, List, Optional


def _has_url(task: str) -> bool:
    return bool(re.search(r"https?://[^\s\]\[\),]+", task, re.I))


def _has_quoted(task: str) -> bool:
    return bool(re.search(r"['\"][^'\"]{2,}['\"]", task))


def needs_clarification(task: str) -> Optional[Dict[str, Any]]:
    """Return a follow-up question when the task cannot be planned as-is."""
    t = (task or "").strip()
    tl = t.lower()
    if not t:
        return {"question": "What would you like me to do, sir?",
                "options": [], "hint": "empty task"}

    # Fast passes — these always carry their own target.
    if _has_url(t) or _has_quoted(t):
        return None
    if re.search(r"\d+\s*[\+\-\*/×÷]\s*\d+", t):
        return None  # arithmetic to crunch
    if re.search(r"\b(screenshot|capture\s+the\s+screen)\b", tl):
        return None
    if re.search(r"\b(notepad|calculator|chrome|excel|word|powerpoint)\b", tl) and \
            re.search(r"\b(open|type|write|start|launch|calculate|compute)\b", tl):
        return None
    if re.search(r"\b(run|show)\b.{0,20}\b(tests?|pytest)\b", tl):
        return None
    if re.search(r"\bgit\s+(status|diff|log|branch)\b", tl):
        return None
    if re.search(r"\b(weather|battery|volume|mute|lock|sleep|shutdown|restart|time|date)\b", tl):
        return None

    # Dangling pronouns — "fix it", "open that", "send it", "delete them".
    m = re.match(r"^\s*(please\s+)?(fix|open|close|delete|remove|send|run|do|check|update|rename|move|copy)\s+(it|that|this|them|those)\s*[?.!]*\s*$", tl)
    if m:
        verb = m.group(2)
        return {"question": f"Which one should I {verb}, sir? Give me a name, a link, or a file.",
                "options": [], "hint": "dangling pronoun"}

    # Summarize/extract with no source.
    if re.match(r"^\s*(summarize|summerize|extract|read|open|translate)\s+(this|that|it)\s*[?.!]*\s*$", tl):
        return {"question": "What should I read, sir — paste a link or tell me the file name?",
                "options": [], "hint": "missing source"}

    # Research with no topic.
    if re.search(r"\bresearch\b", tl) and not re.search(
            r"\b(research|about|on|for)\s+(?!and\b)([a-z]{3,})", tl):
        # Has the word research but nothing shaped like a topic after markers.
        stripped = re.sub(r"\b(research|make|create|generate|write|build|prepare|document|report|word|powerpoint|presentation|ppt|docx|and|a|the|me|please|from|with)\b", "", tl)
        if len(re.sub(r"\s+", "", stripped)) < 4:
            return {"question": "What topic should I research, sir?",
                    "options": [], "hint": "missing topic"}
        return None

    # Bare search with no query.
    if re.match(r"^\s*(search|google|find|look\s*up)(\s+for|\s+about)?\s*[?.!]*\s*$", tl):
        return {"question": "What should I search for, sir?",
                "options": [], "hint": "missing query"}

    # Create file/folder with no name.
    if re.search(r"\bcreate\b.*\bfile\b", tl) and not re.search(
            r"(named|called|[\"']|\.\w{1,5}\b|in\s+\w+)", tl):
        return {"question": "What should I name the file, sir — and what goes inside it?",
                "options": [], "hint": "missing filename"}
    if re.match(r"^\s*(please\s+)?(create|make)\s+(a\s+)?folder\s*[?.!]*\s*$", tl):
        return {"question": "What should I call the folder, sir?",
                "options": [], "hint": "missing folder name"}

    # Messaging with no contact or content.
    if re.search(r"\b(send|message|whatsapp|text)\b", tl) and not re.search(
            r"(to\s+\w+|[\"']|:\s*\w|\+?\d[\d\s\-]{6,})", tl):
        if re.match(r"^\s*(please\s+)?(send|message|text).*", tl) and len(t.split()) <= 6:
            return {"question": "Who should I message, sir — and what should I say?",
                    "options": [], "hint": "missing contact/message"}

    # Scheduled message with no contact ("schedule a message at 6pm" — no 'to').
    if re.search(r"\bschedul\w*\b", tl) and re.search(r"\b(message|whatsapp)\b", tl) and not re.search(
            r"(to\s+\w+|[\"']|:\s*\w|\+?\d[\d\s\-]{6,})", tl):
        return {"question": "Who should I send the scheduled message to, sir — and what should it say?",
                "options": [], "hint": "missing schedule contact/message"}

    # Login with no site.
    if re.search(r"\blog\s*in\b|\b(sign|log)\s*in\b", tl) and not _has_url(t):
        if len(t.split()) <= 8:
            return {"question": "Where should I log in, sir? Paste the login link.",
                    "options": [], "hint": "missing login url"}

    # Download with no link.
    if re.search(r"\bdownload\b", tl) and not _has_url(t):
        if len(t.split()) <= 8:
            return {"question": "What should I download, sir? Paste the link.",
                    "options": [], "hint": "missing download url"}

    # Pure vagueness.
    if re.match(r"^\s*(help|hello|hi|hey|do\s+something|anything|start)\s*[?.!]*\s*$", tl):
        return {"question": ("At your service, sir. What shall I do — research something, "
                             "create a document, run a command, or control an app?"),
                "options": ["Research a topic", "Create a document", "Run the test suite", "Take a screenshot"],
                "hint": "vague task"}

    return None


def apply_answer(task: str, answer: str) -> str:
    """Fold the human's clarification answer back into the task."""
    answer = (answer or "").strip()
    if not answer:
        return task
    return f"{task} [Clarification: {answer}]"


# ─────────────────────────────────────────────────────────────────────────
# Mid-task instruction triage: related change vs independent queued task
# ─────────────────────────────────────────────────────────────────────────

INTERRUPT_WORDS = ("stop", "cancel", "abort", "halt", "wait", "hold on",
                   "hold up", "pause", "interrupt", "never mind", "forget it")

RELATED_MARKERS = ("actually", "instead", "rather", "change", "modify",
                   "update", "correction", "make it", "make the", "add",
                   "remove", "delete", "also", "and then", "then",
                   "after that", "forget that", "skip that", "no wait")

_STOPWORDS = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
              "for", "of", "with", "by", "is", "are", "was", "were", "be",
              "have", "has", "had", "do", "does", "did", "will", "would",
              "could", "should", "may", "might", "can", "must", "i", "you",
              "he", "she", "it", "we", "they", "me", "him", "her", "us",
              "them", "my", "your", "his", "its", "our", "their", "this",
              "that", "these", "those", "what", "when", "where", "who",
              "why", "how", "please", "sir", "just", "now", "then", "than",
              "from", "into", "over", "under", "again", "very", "more",
              "most", "such", "only", "own", "same", "here", "there"}


def is_interruption(text: str) -> bool:
    """True when the text asks to stop/pause the current work."""
    tl = (text or "").lower()
    return any(w in tl for w in INTERRUPT_WORDS)


def _content_words(text: str) -> List[str]:
    # URLs/quoted targets are compared separately (same-target rule); they
    # must not inflate word overlap ("https", "com", "download" everywhere).
    scrubbed = re.sub(r"https?://[^\s\]\[\),]+", " ", text or "")
    scrubbed = re.sub(r"['\"][^'\"]*['\"]", " ", scrubbed)
    words = re.findall(r"[a-z]{3,}", scrubbed.lower())
    return [w for w in words if w not in _STOPWORDS]


def classify_instruction(current_task: str, instruction: str) -> Dict[str, Any]:
    """Decide whether a mid-run command changes the current task (merge +
    restart) or is independent work (queue for after).

    Returns {"related": bool, "reason": str}. Deterministic and offline:
    explicit change-language always merges; otherwise ≥2 shared content
    words (or a shared quoted/URL target) merge; everything else queues.
    """
    instr = (instruction or "").strip()
    if not instr:
        return {"related": False, "reason": "empty"}
    task_words = set(_content_words(current_task))
    instr_words = set(_content_words(instr))
    instr_l = instr.lower()

    for marker in RELATED_MARKERS:
        if marker in instr_l:
            return {"related": True, "reason": f"change language ('{marker}')"}
    # Same explicit target (link, quoted name, filename) → same task.
    for pat in (r"https?://[^\s\]\[\),]+", r"['\"][^'\"]{2,}['\"]",
                r"\b[\w\-]+\.(?:pdf|docx?|pptx?|csv|txt|png|jpe?g)\b"):
        targets = set(re.findall(pat, instr, re.I))
        if targets and targets & set(re.findall(pat, current_task or "", re.I)):
            return {"related": True, "reason": "same target referenced"}
    overlap = task_words & instr_words
    if len(overlap) >= 2:
        shared = ", ".join(sorted(overlap)[:3])
        return {"related": True, "reason": f"shared topic ({shared})"}
    return {"related": False, "reason": "independent task"}
