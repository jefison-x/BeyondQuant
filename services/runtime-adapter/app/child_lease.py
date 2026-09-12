"""BYQ timeout accounting only; execution and scheduling remain DSH-owned."""
from dataclasses import dataclass


@dataclass(slots=True)
class ChildLease:
    parent_id: str
    child_id: str
    call_id: str
    started_at: float
    last_activity_at: float
    last_sequence: int = -1

    def observe(self, sequence: int | None, now: float) -> bool:
        if type(sequence) is not int or sequence < 0 or sequence <= self.last_sequence:
            return False
        self.last_sequence = sequence
        self.last_activity_at = max(self.last_activity_at, now)
        return True

    def expired(self, now: float, inactivity: float, hard_cap: float) -> bool:
        return (hard_cap > 0 and now - self.started_at > hard_cap) or now - self.last_activity_at > inactivity
