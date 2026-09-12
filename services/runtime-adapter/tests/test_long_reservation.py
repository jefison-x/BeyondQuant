from datetime import datetime, timedelta, timezone
import pytest
from app.continuation_budget import validate_reservation


@pytest.mark.parametrize('seconds,allowed', [(7200, True), (86399, True), (86460, False), (-1, False)])
def test_long_reservation_respects_absolute_deadline(seconds, allowed):
    value = dict(schema_version='task-continuation-reservation.v1', reservation_id='continuation_'+'a'*32,
        task_id='task_'+'b'*32, owner='owner', workspace_id='workspace', token_limit=100,
        expires_at=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat())
    if allowed:
        assert validate_reservation(value, owner='owner', workspace='workspace') == value
        with pytest.raises(ValueError):
            validate_reservation(value, owner='foreign', workspace='workspace')
    else:
        with pytest.raises(ValueError):
            validate_reservation(value, owner='owner', workspace='workspace')
