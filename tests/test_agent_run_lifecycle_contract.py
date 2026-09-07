import pytest

from packages.contracts.agent_run_lifecycle import registration_fingerprint, validate_lifecycle_event


def test_registration_digest_binds_every_trusted_identity_component():
    identity = ["alice", "workspace_alice", "agent", "trace", "session", "generation", "key"]
    expected = registration_fingerprint(*identity)
    assert len(expected) == 64
    assert expected == registration_fingerprint(*[" " + item + " " for item in identity])
    for index in range(len(identity)):
        changed = identity.copy()
        changed[index] += "-other"
        assert registration_fingerprint(*changed) != expected


@pytest.mark.parametrize("change", [
    {"root_run_id": "session-instead-of-root"}, {"sequence": True}, {"sequence": 0},
    {"outcome": "queued"}, {"outcome": []}, {"owner_principal": "model-supplied-owner"},
    {"registration_fingerprint": "a" * 64}, {"schema_version": "unknown"},
])
def test_lifecycle_event_rejects_ambiguous_or_expanded_contract(change):
    event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
             "sequence": 2, "outcome": "failed", **change}
    with pytest.raises(ValueError):
        validate_lifecycle_event(event)


def test_registration_and_terminal_evidence_remain_separate():
    event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": "a" * 32,
             "sequence": 1, "outcome": "active"}
    with pytest.raises(ValueError):
        validate_lifecycle_event(event)
    bound = {**event, "registration_fingerprint": "b" * 64}
    assert validate_lifecycle_event(bound) == bound
    terminal = {**event, "sequence": 2, "outcome": "failed"}
    assert validate_lifecycle_event(terminal) == terminal
