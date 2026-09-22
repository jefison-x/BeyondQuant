"""Versioned compatibility boundary for official DSH releases."""

from .types import RuntimeCompatibility, RuntimeObservation


def compatibility_for_release(release: str) -> RuntimeCompatibility:
    if release == "dsh-0.1.5rc1":
        # Repository default since the 0.9 formal default upgrade. The Python SDK
        # public surface is byte-identical to 0.1.2rc1 (docs/evidence/d15), so the
        # observation contract is inherited unchanged.
        from .dsh_015 import Dsh015Compatibility

        return Dsh015Compatibility()
    if release == "dsh-0.1.2rc1":
        # Retained rollback baseline: the archived 0.1.2 image and this boundary
        # stay selectable so the default upgrade is reversible without code drift.
        from .dsh_012 import Dsh012Compatibility

        return Dsh012Compatibility()
    raise ValueError(f"unsupported DSH compatibility release: {release}")


__all__ = [
    "RuntimeCompatibility", "RuntimeObservation",
    "compatibility_for_release",
]
