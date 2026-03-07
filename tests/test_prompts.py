from picobot.agent.prompts import (
    detect_language,
    kb_user_prompt,
    system_base_context,
    tool_protocol_system,
)


def test_detect_language_it():
    assert detect_language("voglio un podcast su AI", default="it") == "it"


def test_detect_language_en():
    assert detect_language("make a podcast about AI", default="it") == "en"


def test_system_base_context():
    text = system_base_context("it")
    assert "Picobot" in text


def test_kb_user_prompt():
    text = kb_user_prompt(lang="it", question="ciao?", context="contesto")
    assert "DOMANDA" in text
    assert "CONTESTO" in text


def test_tool_protocol_system():
    text = tool_protocol_system(["tts", "stt"])
    assert "tts" in text
    assert "stt" in text
