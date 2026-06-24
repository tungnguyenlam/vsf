"""Tests for `load_env` — the single source of truth for loading `.env` keys."""

import os

from src.pipeline import Utils


def test_load_env_populates_from_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("VSF_TEST_KEY=from_dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VSF_TEST_KEY", raising=False)

    Utils.load_env()

    assert os.environ.get("VSF_TEST_KEY") == "from_dotenv"


def test_load_env_does_not_override_existing_environment(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("VSF_TEST_KEY=from_dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VSF_TEST_KEY", "from_export")

    Utils.load_env()

    # An explicit export wins over .env, so a manual override still works.
    assert os.environ.get("VSF_TEST_KEY") == "from_export"


def test_load_env_is_safe_without_dotenv_installed(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "dotenv":
            raise ImportError("simulated missing python-dotenv")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    # Must not raise when python-dotenv is unavailable.
    Utils.load_env()
