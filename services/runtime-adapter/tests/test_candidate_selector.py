"""D15 candidate selector: 0.1.5 is reachable explicitly, 0.1.2 stays default."""

from app.compat import compatibility_for_release


def test_production_default_still_selects_the_012_boundary() -> None:
    assert compatibility_for_release("dsh-0.1.2rc1").family == "dsh-0.1.2"


def test_candidate_015_is_reachable_by_explicit_selector() -> None:
    assert compatibility_for_release("dsh-0.1.5rc1").family == "dsh-0.1.5"


def test_unknown_release_fails_closed() -> None:
    try:
        compatibility_for_release("dsh-0.1.5-rc.2")
    except ValueError as error:
        assert "unsupported DSH compatibility release" in str(error)
    else:
        raise AssertionError("unqualified npm-only release must not resolve")
