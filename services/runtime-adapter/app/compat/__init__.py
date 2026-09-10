"""Versioned compatibility boundary for official DSH releases."""

from .types import RuntimeCompatibility, RuntimeObservation


def compatibility_for_release(release: str) -> RuntimeCompatibility:
    if release == "dsh-0.1.2rc1":
        # The only supported runtime installs the exact 0.1.2 wheels.
        from .dsh_012 import Dsh012Compatibility

        return Dsh012Compatibility()
    raise ValueError(f"unsupported DSH compatibility release: {release}")


__all__ = [
    "RuntimeCompatibility", "RuntimeObservation",
    "compatibility_for_release",
]
