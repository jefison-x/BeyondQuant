"""Versioned compatibility boundary for official DSH releases."""

from .dsh_011 import Dsh011Compatibility
from .types import RuntimeCompatibility, RuntimeObservation


def compatibility_for_release(release: str) -> RuntimeCompatibility:
    if release == "dsh-0.1.1rc1":
        return Dsh011Compatibility()
    if release == "dsh-0.1.2rc1":
        # Keep the candidate-only SDK/runtime imports outside the default
        # 0.1.1 process. The candidate image installs the exact 0.1.2 wheels.
        from .dsh_012 import Dsh012Compatibility

        return Dsh012Compatibility()
    raise ValueError(f"unsupported DSH compatibility release: {release}")


__all__ = [
    "Dsh011Compatibility", "RuntimeCompatibility", "RuntimeObservation",
    "compatibility_for_release",
]
