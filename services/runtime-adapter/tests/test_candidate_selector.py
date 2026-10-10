"""Only the manifest-selected ACP family is selectable online."""

import pytest

from app.compat import ACP_COMPATIBILITY_FAMILY, compatibility_for_release


def test_authoritative_acp_family_selects_the_acp_compatibility(monkeypatch) -> None:
    class SyntheticAcpCompatibility:
        family = ACP_COMPATIBILITY_FAMILY

    from app.compat import dsh_acp
    monkeypatch.setattr(dsh_acp, "DshAcpCompatibility", SyntheticAcpCompatibility)
    compatibility = compatibility_for_release(ACP_COMPATIBILITY_FAMILY)
    assert isinstance(compatibility, SyntheticAcpCompatibility)
    assert compatibility.family == ACP_COMPATIBILITY_FAMILY


@pytest.mark.parametrize("legacy_release", ["dsh-0.1.2rc1", "dsh-0.1.5rc1"])
def test_sdk_releases_are_not_online_compatibility_choices(legacy_release: str) -> None:
    with pytest.raises(ValueError, match="unsupported DSH compatibility release"):
        compatibility_for_release(legacy_release)


def test_unknown_release_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported DSH compatibility release"):
        compatibility_for_release("dsh-v0.2.0-rc.2")
