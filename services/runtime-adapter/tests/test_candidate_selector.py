"""Selector: the promoted 0.1.5 default and the retained 0.1.2 rollback."""

from app.compat import compatibility_for_release


def test_retained_rollback_selects_the_012_boundary() -> None:
    assert compatibility_for_release("dsh-0.1.2rc1").family == "dsh-0.1.2"


def test_promoted_default_selects_the_015_boundary() -> None:
    assert compatibility_for_release("dsh-0.1.5rc1").family == "dsh-0.1.5"


def test_unknown_release_fails_closed() -> None:
    try:
        compatibility_for_release("dsh-0.1.5-rc.2")
    except ValueError as error:
        assert "unsupported DSH compatibility release" in str(error)
    else:
        raise AssertionError("unqualified npm-only release must not resolve")
