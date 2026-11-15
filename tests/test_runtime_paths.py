from pathlib import Path

from vela.settings import DATA_DIR, writable_data_dir


def test_writable_data_dir_uses_vercel_tmp_and_supports_override(monkeypatch):
    monkeypatch.delenv("VELA_WRITABLE_DATA_DIR", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    assert writable_data_dir() == Path("/tmp/vela")

    monkeypatch.delenv("VERCEL")
    assert writable_data_dir() == DATA_DIR

    monkeypatch.setenv("VELA_WRITABLE_DATA_DIR", "/custom/vela")
    assert writable_data_dir() == Path("/custom/vela")
