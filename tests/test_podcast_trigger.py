from picobot.config.schema import Config
from picobot.tools.podcast import detect_podcast_request


def test_detect_podcast_request_it():
    cfg = Config()
    cfg.podcast.enabled = True
    t = "voglio un podcast su intelligenza artificiale"
    got = detect_podcast_request(t, cfg)
    assert got is not None
    topic, lang = got
    assert lang == "it"
    assert "intelligenza" in topic.lower()


def test_detect_podcast_request_en():
    cfg = Config()
    cfg.podcast.enabled = True
    t = "I want a podcast about space telescopes"
    got = detect_podcast_request(t, cfg)
    assert got is not None
    topic, lang = got
    assert lang == "en"
    assert "space" in topic.lower()
