"""The single authoritative DSH compatibility family used online."""

from .types import RuntimeCompatibility, RuntimeObservation

ACP_COMPATIBILITY_FAMILY = "dsh-v0.2.0-rc.2-acp"


def compatibility_for_release(release: str) -> RuntimeCompatibility:
    if release != ACP_COMPATIBILITY_FAMILY:
        raise ValueError(f"unsupported DSH compatibility release: {release}")
    from .dsh_acp import DshAcpCompatibility

    return DshAcpCompatibility()


__all__ = [
    "ACP_COMPATIBILITY_FAMILY", "RuntimeCompatibility", "RuntimeObservation",
    "compatibility_for_release",
]
