"""ADR-0085 P3 trusted runtime-adapter invocation of one bounded judgment turn.

The Runtime Adapter is trusted BYQ infrastructure. For a genuine
research-judgment stage it:

1. admits exactly one bounded model call through the named Backend seam (the
   server derives the 1-based count and the two-call bound; the adapter never
   supplies a count);
2. runs the DSH turn INSIDE the single bounded foreground judgment role
   ``RESEARCH_JUDGMENT_PERSONA_TOOL`` (``plugins/dsh-byq`` composition). That
   role is itself a ``@deepseek-ai/dsh-tool-subagent`` foreground instance
   (``provider: spawn``, ``enableRunInBackground: false``) with ``maxDepth: 0``,
   so it cannot spawn further subagents and cannot restore the historical
   eight-call investigation. Its ``toolFilter`` is a static exact read-only
   allowlist, so the model invoked through it has no
   write/approval/execute/routing/identity tool and no proposal tool. One call
   counts against the Backend per-stage durable admission bound of two;
3. submits the CLOSED model result to the named server-side result operation,
   which atomically validates/commits an accepted proposal, records the
   authoritative durable-progress receipt, completes the call admission and
   converges a terminal ResearchTask.

There is no generic plan/proposal/event write route and no agent-facing write.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

# The dedicated bounded judgment persona's model-facing tool name. It MUST match
# the generated composition's `research-judgment-turn` entry; an architecture
# test fails CI on divergence.
RESEARCH_JUDGMENT_PERSONA_TOOL = "byq_research_judgment_turn"
_RESULT_FIELDS = frozenset({"proposal", "durable_evidence"})

# ADR-0085 P4: the bounded judgment turn must reach ONLY the isolated read-only
# MCP endpoint. The trusted Runtime Adapter derives it from dedicated variables
# and fails closed if they are missing or collide with the Product MCP endpoint
# or credential, so a misconfiguration can never load the full 82-tool surface.
_READ_ONLY_URL_ENV = "BYQ_MCP_READ_ONLY_URL"
_READ_ONLY_TOKEN_ENV = "BYQ_MCP_READ_ONLY_TOKEN"
_PRODUCT_URL_ENV = "BYQ_MCP_URL"
_PRODUCT_TOKEN_ENV = "BYQ_MCP_TOKEN"


class ResearchJudgmentError(RuntimeError):
    """A bounded research-judgment invocation failed closed."""


class ResearchJudgmentInProgress(ResearchJudgmentError):
    """The same durable attempt is already admitted by a live owner.

    A duplicate/concurrent request must NOT terminate the original turn; it waits
    or returns an explicit in-progress. There is no cross-process lease yet, so we
    cannot prove the old owner is terminal and therefore never mutate state here.
    """


def resolve_read_only_mcp_endpoint(env) -> dict:
    """Derive the isolated read-only MCP endpoint or fail closed.

    A missing read-only URL/token, or a read-only endpoint/credential that is the
    same as the Product MCP, is a configuration error: the bounded persona could
    otherwise discover the full Product surface.
    """

    url = (env.get(_READ_ONLY_URL_ENV) or "").strip()
    token = (env.get(_READ_ONLY_TOKEN_ENV) or "").strip()
    if not url or not token:
        raise ResearchJudgmentError(
            "read-only MCP endpoint is not configured for the bounded judgment turn")
    product_url = (env.get(_PRODUCT_URL_ENV) or "").strip()
    product_token = (env.get(_PRODUCT_TOKEN_ENV) or "").strip()
    if url == product_url or token == product_token:
        raise ResearchJudgmentError(
            "read-only MCP endpoint or credential collides with the Product MCP")
    return {"url": url, "token": token}


def _http_post(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def _call(post, url: str, payload: dict, headers: dict, timeout: float) -> dict:
    """Invoke the trusted channel and fail closed on any transport/response error."""

    try:
        value = post(url, payload, headers, timeout)
    except ResearchJudgmentError:
        raise
    except urllib.error.HTTPError as error:
        raise ResearchJudgmentError(
            f"research judgment backend rejected the request: {error.code}") from error
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as error:
        raise ResearchJudgmentError("research judgment backend unavailable") from error
    if not isinstance(value, dict):
        raise ResearchJudgmentError("research judgment backend returned an invalid response")
    return value


def enforce_bounded_result_shape(model_result: object) -> dict:
    """Reject anything that is not a closed proposal/no-progress result."""

    if not isinstance(model_result, dict) or set(model_result) - _RESULT_FIELDS:
        raise ResearchJudgmentError("invalid closed research judgment result")
    if model_result.get("proposal") is not None and not isinstance(model_result["proposal"], dict):
        raise ResearchJudgmentError("invalid closed research judgment result")
    return model_result


def admit_research_judgment_turn(
    *, backend_url: str, task_id: str, trusted_headers: dict, call_identity: str,
    attempt: str | None = None, transport=None, timeout: float = 8.0,
) -> dict:
    """Reserve one bounded model call; the backend derives the count and bound."""

    post = transport or _http_post
    payload: dict = {"call_identity": call_identity}
    if attempt is not None:
        payload["attempt_binding"] = attempt
    return _call(
        post, f"{backend_url}/internal/research-judgment/{task_id}/admit",
        payload, trusted_headers, timeout)


def submit_research_judgment_result(
    *, backend_url: str, task_id: str, trusted_headers: dict, call_identity: str,
    model_result: object, transport=None, timeout: float = 8.0,
) -> dict:
    """Submit the CLOSED model result to the atomic server-side result operation."""

    result = enforce_bounded_result_shape(model_result)
    payload = {
        "call_identity": call_identity,
        "durable_evidence": result.get("durable_evidence", {"kind": "none"}),
    }
    if result.get("proposal") is not None:
        payload["proposal"] = result["proposal"]
    post = transport or _http_post
    return _call(
        post, f"{backend_url}/internal/research-judgment/{task_id}/result",
        payload, trusted_headers, timeout)


def run_bounded_research_judgment(
    *, backend_url: str, task_id: str, trusted_headers: dict, call_identity: str,
    turn_runner, attempt: str | None = None, transport=None, timeout: float = 8.0,
) -> dict:
    """Admit, run the turn inside the bounded persona, then submit the result.

    ``turn_runner`` receives the admission (with the bounded stage input) and the
    bounded persona tool name, and MUST run the DSH turn inside that persona so
    the model cannot reach any write tool.

    Exactly-once behavior across interrupts:

    * a COMPLETED admission returns its stored receipt and runs NO model turn (a
      lost response or a late retry after the plan advanced is a free replay);
    * an existing in-flight admission is NOT terminated by a duplicate/concurrent
      request: we cannot prove the original owner is dead, so we fail closed with
      ``ResearchJudgmentInProgress`` and leave all business state unchanged (to be
      surfaced as an explicit in-progress). Convergence would require a verifiable
      lease/receipt, which does not exist yet; a real cross-process resume is NOT
      claimed;
    * only a freshly created admission runs the model turn.
    """

    admission = admit_research_judgment_turn(
        backend_url=backend_url, task_id=task_id, trusted_headers=trusted_headers,
        call_identity=call_identity, attempt=attempt, transport=transport, timeout=timeout)
    if admission.get("status") == "completed":
        stored = admission.get("receipt") if isinstance(admission.get("receipt"), dict) else {}
        return {**stored, "replayed": True, "model_turn_skipped": True}
    if admission.get("created") is False:
        raise ResearchJudgmentInProgress(
            "bounded judgment attempt is already admitted by a live owner")
    model_result = turn_runner(admission, RESEARCH_JUDGMENT_PERSONA_TOOL)
    return submit_research_judgment_result(
        backend_url=backend_url, task_id=task_id, trusted_headers=trusted_headers,
        call_identity=call_identity, model_result=model_result, transport=transport,
        timeout=timeout)
