"""Versioned compatibility boundary for official DSH releases."""

from .types import RuntimeCompatibility, RuntimeObservation


def compatibility_for_release(release: str) -> RuntimeCompatibility:
    if release == "dsh-0.1.2rc1":
        # Production default: the only supported runtime installs the exact 0.1.2 wheels.
        from .dsh_012 import Dsh012Compatibility

        return Dsh012Compatibility()
    if release == "dsh-0.1.5rc1":
        # D15 candidate: isolated selector, never the production default. The D15-0
        # ledger records the native 0.1.5 continuity surfaces; this class only
        # inherits the unchanged SDK contract until D15-G qualifies adoption.
        from .dsh_015 import Dsh015Compatibility

        return Dsh015Compatibility()
    raise ValueError(f"unsupported DSH compatibility release: {release}")


__all__ = [
    "RuntimeCompatibility", "RuntimeObservation",
    "compatibility_for_release",
]
