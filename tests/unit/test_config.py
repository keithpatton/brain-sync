"""Tests for brain_sync.config — canonical config load/save."""

from __future__ import annotations

import json
import threading

import pytest

from brain_sync.config import load_config, save_config

pytestmark = pytest.mark.unit


class TestLoadConfig:
    def test_returns_empty_dict_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", tmp_path / "nope.json")
        assert load_config() == {}

    def test_returns_empty_dict_on_invalid_json(self, tmp_path, monkeypatch):
        bad = tmp_path / "config.json"
        bad.write_text("not json!", encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", bad)
        assert load_config() == {}

    def test_loads_valid_config(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"brains": ["/tmp/brain"]}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", cfg_file)
        result = load_config()
        assert result == {"brains": ["/tmp/brain"]}

    def test_returns_empty_dict_on_empty_file(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("", encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", cfg_file)
        assert load_config() == {}


class TestSaveConfig:
    def test_creates_dir_and_file(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "new_dir"
        cfg_file = cfg_dir / "config.json"
        monkeypatch.setattr("brain_sync.config.CONFIG_DIR", cfg_dir)
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", cfg_file)

        save_config({"key": "value"})

        assert cfg_file.exists()
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert data == {"key": "value"}

    def test_overwrites_existing(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"old": True}), encoding="utf-8")
        monkeypatch.setattr("brain_sync.config.CONFIG_DIR", cfg_dir)
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", cfg_file)

        save_config({"new": True})

        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert data == {"new": True}
        assert "old" not in data


class TestRoundTrip:
    def test_save_then_load(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path
        cfg_file = tmp_path / "config.json"
        monkeypatch.setattr("brain_sync.config.CONFIG_DIR", cfg_dir)
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", cfg_file)

        original = {"brains": ["/a", "/b"], "log_level": "DEBUG"}
        save_config(original)
        loaded = load_config()
        assert loaded == original


class TestThreadSafety:
    def test_concurrent_save_load(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path
        cfg_file = tmp_path / "config.json"
        monkeypatch.setattr("brain_sync.config.CONFIG_DIR", cfg_dir)
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", cfg_file)

        save_config({"initial": True})
        errors: list[Exception] = []

        def writer():
            try:
                for i in range(20):
                    save_config({"counter": i})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(20):
                    result = load_config()
                    assert isinstance(result, dict)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
