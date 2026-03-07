from picobot.config.schema import Config


def test_config_defaults():
    cfg = Config()
    assert cfg.default_language in {"it", "en"}
    assert cfg.default_kb_name
    assert cfg.qdrant.router_collection
    assert cfg.qdrant.docs_collection
