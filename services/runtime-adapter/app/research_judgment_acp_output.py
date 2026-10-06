"""Closed, bounded result capture for one dedicated ACP judgment root.

Only release-neutral compatibility observations enter this business parser.
Provider usage and request budgets must be proven at the provider boundary;
this parser is solely the final result shape gate.
"""

from __future__ import annotations

import json
from typing import NoReturn

from packages.contracts.research_judgment import PROPOSAL_MAX_BYTES, validate_proposal

from .compat.types import RuntimeObservation
from .research_judgment import ResearchJudgmentError

_MAX_RESULT_TEXT_BYTES = PROPOSAL_MAX_BYTES + 4096
_RESULT_FIELDS = frozenset({"proposal", "durable_evidence"})


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate result key")
        value[key] = item
    return value


def _reject_constant(_value: str) -> object:
    raise ValueError("non-finite result number")


class AcpJudgmentRootOutput:
    """Capture the final closed root answer after a nominally completed ACP prompt.

    A dedicated judgment root that uses its five read-only tools emits
    intermediate assistant messages within one turn. Only the last COMPLETE root
    message is accepted, and only after a normal completed turn; intermediate
    messages are process evidence and never produce a result.
    """

    def __init__(self, native_root_session_id: str) -> None:
        if not isinstance(native_root_session_id, str) or not native_root_session_id:
            raise ValueError("native ACP judgment root identity is required")
        self.native_root_session_id = native_root_session_id
        self._answer: str | None = None
        self._terminal_reason: str | None = None
        self._started = False
        self._ended = False
        self._invalid = False

    def _fail(self, reason: str) -> NoReturn:
        self._invalid = True
        raise ResearchJudgmentError(reason)

    def observe(self, observation: RuntimeObservation) -> None:
        if self._invalid:
            self._fail("ACP judgment root output is invalid")
        if not isinstance(observation, RuntimeObservation):
            self._fail("ACP judgment observation is invalid")
        if (observation.session_id is not None
                and observation.session_id != self.native_root_session_id):
            self._fail("ACP judgment foreign session update is not allowed")
        if observation.kind == "turn.start" and observation.root_session:
            if (observation.session_id != self.native_root_session_id
                    or self._started or self._ended):
                self._fail("ACP judgment root start update is invalid")
            self._started = True
        elif observation.kind == "assistant.message":
            # A tool-use turn may emit intermediate root messages (narration and
            # tool-call protocol) before the final closed answer. Each observed
            # message is a COMPLETE message aggregated from official streaming
            # chunks, never a single chunk. Only the last complete message is a
            # candidate result, and it is accepted strictly after normal
            # completion; intermediate messages are process evidence only and
            # never produce a result or trigger a business action.
            if (not observation.root_session
                    or observation.session_id != self.native_root_session_id
                    or not observation.message_id or not isinstance(observation.answer_text, str)
                    or not self._started or self._ended):
                self._fail("ACP judgment root answer update is invalid")
            if len(observation.answer_text.encode("utf-8")) > _MAX_RESULT_TEXT_BYTES:
                self._fail("ACP judgment result exceeds its text bound")
            self._answer = observation.answer_text
        elif observation.kind == "turn.end" and observation.root_session:
            if (observation.session_id != self.native_root_session_id
                    or not self._started or self._ended):
                self._fail("ACP judgment root terminal update is invalid")
            self._ended = True
            self._terminal_reason = observation.terminal_reason

    def result(self, finish_reason: str) -> dict:
        if (self._invalid or finish_reason != "completed" or not self._started or not self._ended
                or self._terminal_reason != "completed"
                or self._answer is None):
            raise ResearchJudgmentError("ACP judgment root did not return a completed result")
        try:
            parsed = json.loads(self._answer, object_pairs_hook=_unique_object,
                                parse_constant=_reject_constant)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ResearchJudgmentError("ACP judgment root result is not exact JSON") from error
        if (not isinstance(parsed, dict) or set(parsed) != _RESULT_FIELDS
                or parsed["durable_evidence"] != {"kind": "none"}
                or (parsed["proposal"] is not None and not isinstance(parsed["proposal"], dict))):
            raise ResearchJudgmentError("ACP judgment root result has invalid fields")
        if parsed["proposal"] is not None:
            try:
                validate_proposal(parsed["proposal"])
            except ValueError as error:
                raise ResearchJudgmentError("ACP judgment root proposal is invalid") from error
        return parsed
