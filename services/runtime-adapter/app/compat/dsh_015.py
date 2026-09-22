"""Repository-default boundary for the official DSH 0.1.5 bundled runtime.

The Python ``deepseek-harness-sdk`` surface is byte-identical between
``0.1.2rc1`` and ``0.1.5rc1`` (see ``docs/evidence/d15/upgrade-recon.v1.json``),
so the adaptive notification/tool observation contract is inherited unchanged
from :mod:`services.runtime_adapter.app.compat.dsh_012`.

What changed in 0.1.5 is the *bundled native runtime*: Session V2/V3 format
migration, handle-based session persistence, cross-process write leases and
continuable subagents. Adopting those native capabilities is the subject of
D15-2..D15-G and is deliberately **not** wired into this compatibility class
yet; wiring them before qualification would create a second continuity
implementation (forbidden by ADR-0079/ADR-0081 and the R3 freeze).

Since the 0.9 formal default upgrade this boundary is the repository default
(``BYQ_DSH_COMPATIBILITY_RELEASE`` default ``dsh-0.1.5rc1``); ``dsh-0.1.2rc1``
remains the retained rollback baseline. The default upgrade does not deploy to
production and does not adopt native continuity.
"""

from __future__ import annotations

from .dsh_012 import Dsh012Compatibility


class Dsh015Compatibility(Dsh012Compatibility):
    """Repository-default 0.1.5 boundary; inherits the unchanged SDK contract."""

    family = "dsh-0.1.5"


__all__ = ["Dsh015Compatibility"]
