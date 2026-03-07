from picobot.config.schema import Config
from picobot.tools.podcast import detect_podcast_request


def test_detect_podcast_request_it():
    cfg = Config()
    result = detect_podcast_request("voglio un podcast su sistemi multi-agent", cfg)
    assert result is not None

    topic, lang = result
    assert "sistemi multi-agent" in topic
    assert lang == "it"


def test_detect_podcast_request_en():
    cfg = Config()
    result = detect_podcast_request("make a podcast about local-first agents", cfg)
    assert result is not None

    topic, lang = result
    assert "local-first agents" in topic
    assert lang == "en"
