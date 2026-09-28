import pytest

from shared import config


def test_require_paths_raises_with_missing_variable_name_when_unset(monkeypatch):
    monkeypatch.setattr(config, "LSTM_CHECKPOINT_PATH", None)

    with pytest.raises(RuntimeError, match="LSTM_CHECKPOINT_PATH"):
        config.require_paths("LSTM_CHECKPOINT_PATH")


def test_require_paths_lists_every_missing_variable(monkeypatch):
    monkeypatch.setattr(config, "LSTM_CHECKPOINT_PATH", None)
    monkeypatch.setattr(config, "FEATURE_STATS_PATH", None)

    with pytest.raises(RuntimeError) as exc_info:
        config.require_paths("LSTM_CHECKPOINT_PATH", "FEATURE_STATS_PATH")

    assert "LSTM_CHECKPOINT_PATH" in str(exc_info.value)
    assert "FEATURE_STATS_PATH" in str(exc_info.value)


def test_require_paths_passes_when_variable_is_set(monkeypatch):
    monkeypatch.setattr(config, "LSTM_CHECKPOINT_PATH", "/tmp/best_model.pt")

    config.require_paths("LSTM_CHECKPOINT_PATH")
