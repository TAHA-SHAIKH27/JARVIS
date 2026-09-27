"""Tests for reply-language detection + TTS voice selection.

JARVIS must speak Hindi/Urdu/Marathi/French/Spanish replies with a matching
voice instead of reading everything with the English voice.
"""
from backend.agent.lang_detect import (
    LANGS, detect_lang, select_voice_for_lang,
)


def test_hindi_script_and_hint():
    assert detect_lang("टीचर ने कहा", "tell me a hindi joke") == "hi"
    assert detect_lang("मैंने संतोष को बुलाया") == "hi"


def test_marathi_markers_beat_hindi_default():
    assert detect_lang("तुम्ही कसे आहात") == "mr"
    assert detect_lang("मला पाहिजे आहे") == "mr"
    # Devanagari without Marathi markers stays Hindi.
    assert detect_lang("यह क्या है") == "hi"


def test_urdu_script_and_hint():
    assert detect_lang("آپ کیسے ہیں", "urdu me batao") == "ur"
    assert detect_lang("اردو میں بتاؤ") == "ur"


def test_french_spanish_hints_and_accents():
    assert detect_lang("bla bla", "tell me a joke in french") == "fr"
    assert detect_lang("bla bla", "tell me a joke in spanish") == "es"
    assert detect_lang("¿cómo estás?", "tell me a joke") == "es"
    assert detect_lang("c'est la vie, garçon", "tell me a joke") == "fr"


def test_english_default_never_raises():
    assert detect_lang("Certainly, sir.") == "en"
    assert detect_lang("") == "en"
    assert detect_lang(None) == "en"
    assert set(LANGS) == {"hi", "mr", "ur", "en", "fr", "es"}


def test_select_voice_prefers_lcid_then_name():
    voices = [
        {"id": "v-en", "name": "Microsoft David", "language": "409"},
        {"id": "v-hi", "name": "Microsoft Swara", "language": "439"},
    ]
    assert select_voice_for_lang(voices, "hi")["id"] == "v-hi"
    assert select_voice_for_lang(voices, "en")["id"] == "v-en"
    named = [{"id": "x", "name": "Hindi Female Voice", "language": "999"}]
    assert select_voice_for_lang(named, "hi")["id"] == "x"
    assert select_voice_for_lang(voices, "mr") is None
    assert select_voice_for_lang([], "hi") is None
    assert select_voice_for_lang(None, "hi") is None


def test_speak_accepts_lang_without_sapi():
    from backend.agent.voice import VoiceSystem
    vs = VoiceSystem()
    try:
        assert vs.speak("नमस्ते", lang="hi") is True
        assert vs.speak("hello") is True
    finally:
        vs.clear_queue()


def test_command_response_carries_speak_lang():
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app)
    res = client.post("/api/command", json={"prompt": "clear chat"})
    assert res.status_code == 200
    assert res.json()["speak_lang"] == "en"
