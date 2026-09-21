"""Gateway forwarding of the closed, Backend-minted recovery authority.

The Gateway is a transport, never an authority. It may forward the exact closed
``recovery_attempt`` carrier the Backend minted inside the task-continuation
reservation; it MUST NOT invent, extend, re-order or default any field, and it
MUST NOT construct a carrier of its own (no client/model input, no session id,
no epoch). A malformed or unknown-field carrier is rejected so the turn pauses.
"""

from __future__ import annotations

from packages.contracts import business_recovery as contract


def closed_recovery_carrier(reservation: object) -> dict:
    """Return the reservation with only a validated closed recovery carrier.

    A reservation without ``recovery_attempt`` is returned unchanged (ordinary
    continuation). A reservation with one must carry exactly the closed field set;
    anything else fails closed.
    """

    if not isinstance(reservation, dict):
        raise ValueError("invalid continuation reservation")
    if "recovery_attempt" not in reservation:
        return dict(reservation)
    carrier = contract.validate_recovery_carrier(reservation["recovery_attempt"])
    return {**reservation, "recovery_attempt": carrier}
