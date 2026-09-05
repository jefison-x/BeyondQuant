import pytest

from app.engineering import validate_worktree_path


def test_configurable_declared_worktree_root(monkeypatch):
    monkeypatch.setenv("BYQ_ENGINEERING_WORKTREE_ROOT", "/tmp/byq-engineering-tests")
    assert validate_worktree_path("/tmp/byq-engineering-tests/feature") == "/tmp/byq-engineering-tests/feature"


@pytest.mark.parametrize("value", [
    "/tmp/byq-engineering-tests", "/tmp/byq-engineering-tests-other/feature",
    "/tmp/byq-engineering-tests/../outside", "relative/path", "/home/jefison/projects/BeyondQuant",
])
def test_declared_path_rejects_escape(monkeypatch, value):
    monkeypatch.setenv("BYQ_ENGINEERING_WORKTREE_ROOT", "/tmp/byq-engineering-tests")
    with pytest.raises(ValueError, match="worktree"):
        validate_worktree_path(value)


@pytest.mark.parametrize("root", ["/", "/tmp", "/var/tmp", "/home", "/home/jefison", "/home/another-user", "/home/jefison/projects",
    "/home/jefison/projects/BeyondQuant", "/home/jefison/projects/BeyondQuant-community", "relative", "/tmp/work/../root"])
def test_broad_or_protected_root_is_rejected(monkeypatch, root):
    monkeypatch.setenv("BYQ_ENGINEERING_WORKTREE_ROOT", root)
    with pytest.raises(ValueError, match="root"):
        validate_worktree_path(root + "/feature")
