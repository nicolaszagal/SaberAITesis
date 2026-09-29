import pytest

from shared import config


def test_require_paths_raises_with_missing_variable_name_when_unset(monkeypatch):
    monkeypatch.setattr(config, "MODEL_RUN_DIR", None)

    with pytest.raises(RuntimeError, match="MODEL_RUN_DIR"):
        config.require_paths("MODEL_RUN_DIR")


def test_require_paths_lists_every_missing_variable(monkeypatch):
    monkeypatch.setattr(config, "MODEL_RUN_DIR", None)
    monkeypatch.setattr(config, "FEATURE_STATS_PATH", None)

    with pytest.raises(RuntimeError) as exc_info:
        config.require_paths("MODEL_RUN_DIR", "FEATURE_STATS_PATH")

    assert "MODEL_RUN_DIR" in str(exc_info.value)
    assert "FEATURE_STATS_PATH" in str(exc_info.value)


def test_require_paths_passes_when_variable_is_set(monkeypatch):
    monkeypatch.setattr(config, "MODEL_RUN_DIR", "/tmp/20260928_141021")

    config.require_paths("MODEL_RUN_DIR")
