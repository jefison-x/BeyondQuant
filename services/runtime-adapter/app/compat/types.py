from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    """Bounded Adapter-internal view of one release-specific notification."""

    kind: str
    session_id: str | None = None
    root_session: bool = False
    runtime_activity: bool = False
    status: str | None = None
    terminal_reason: str | None = None
    message_id: str | None = None
    answer_text: str | None = None
    call_id: str | None = None
    tool_name: str | None = None
    tool_failed: bool = False
    tool_result: dict[str, Any] | None = None
    completed_call_ids: tuple[str, ...] = ()
    parent_session_id: str | None = None
    child_session_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class RuntimeCompatibility(Protocol):
    """Internal seam implemented by one exact DSH protocol family."""

    family: str

    def runtime_command(self, runtime_root: Path, node: str) -> tuple[str, ...]: ...

    def build_harness(
        self, *, provider: str, model: str, composition: Path, session_root: Path,
        runtime_command: tuple[str, ...], environment: dict[str, str],
    ) -> Any: ...

    def start(self, harness: Any) -> None: ...

    def prompt(
        self, harness: Any, session_id: str, content: str,
        on_notification: Callable[[object], None],
    ) -> str: ...

    def close(self, harness: Any) -> None: ...

    def observe(self, notification: object, *, root_session_id: str) -> RuntimeObservation: ...
