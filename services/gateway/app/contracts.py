from __future__ import annotations

import sys
from pathlib import Path


_HERE = Path(__file__).resolve()
_PACKAGE_ROOT_CANDIDATES = (
    _HERE.parents[3] / "packages" if len(_HERE.parents) > 3 else None,
    _HERE.parents[1] / "packages" if len(_HERE.parents) > 1 else None,
    Path("/app/packages"),
)
for _candidate in _PACKAGE_ROOT_CANDIDATES:
    if _candidate is not None and _candidate.is_dir():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from contracts.workflow_trace import (  # noqa: E402
    WorkflowTraceEvent,
    validate_workflow_trace_event,
)

__all__ = ["WorkflowTraceEvent", "validate_workflow_trace_event"]
