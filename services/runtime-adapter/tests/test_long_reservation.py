from datetime import datetime, timedelta, timezone

import pytest
from app.continuation_budget import validate_reservation
from packages.contracts.continuation_request import profile_binding, request_limits


@pytest.mark.parametrize("seconds,allowed", [(7200, True), (86399, True), (86460, False), (-1, False)])
def test_business_reservation_expiry_respects_its_own_hard_deadline(seconds, allowed):
    value = {
        "schema_version": "task-continuation-reservation.v2",
        "reservation_id": "continuation_" + "a" * 32,
        "task_id": "task_" + "b" * 32,
        "owner": "owner",
        "workspace_id": "workspace",
        "execution_profile": profile_binding(),
        "request_limits": request_limits(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(),
    }
    if allowed:
        assert validate_reservation(value, owner="owner", workspace="workspace") == value
        with pytest.raises(ValueError, match="ownership"):
            validate_reservation(value, owner="foreign", workspace="workspace")
    else:
        with pytest.raises(ValueError):
            validate_reservation(value, owner="owner", workspace="workspace")
