import pytest

from app import main


@pytest.fixture(autouse=True)
def current_runtime_authority(monkeypatch):
    """Unit tests start at the post-fence application boundary by default."""
    monkeypatch.setattr(main, "_runtime_authority_state", {
        "ready": True,
        "boot_id": "a" * 32,
        "authority_epoch": 1,
    })
    monkeypatch.setattr(main, "_sync_runtime_authority", lambda: main._runtime_authority_snapshot())
    monkeypatch.setenv("BYQ_RUNTIME_AUTHORITY_TOKEN", "test-runtime-authority-token")
