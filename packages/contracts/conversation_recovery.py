"""Closed, bounded public task recovery; no private runtime or domain state."""
from __future__ import annotations

import json
import re

RECOVERY_VERSION = "conversation-recovery.v2"
MAX_UNANSWERED_CHARS = 6000
FAILURE_CODES = frozenset({
    "runtime-no-progress-timeout", "runtime-run-timeout", "runtime-subagent-timeout",
    "model-run-failed", "cancelled", "result-discarded", "unknown",
})
CONTINUATIONS = frozenset({"继续", "继续吧", "请继续", "继续处理", "接着做", "接着研究", "重试", "再试一次", "continue", "retry"})


def is_continuation(value: str) -> bool:
    return value.strip().rstrip("。！!？?").casefold() in CONTINUATIONS


def valid_identity(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is not None


def normalize_recovery(value: object, session_id: str, trace_id: str) -> dict | None:
    if value is None:
        return None
    keys = {"schema_version", "session_id", "trace_id", "status", "unanswered_turn", "failure"}
    if not isinstance(value, dict) or set(value) != keys or value["schema_version"] != RECOVERY_VERSION:
        raise ValueError("invalid conversation recovery schema")
    if not valid_identity(session_id) or not valid_identity(trace_id) or value["session_id"] != session_id or value["trace_id"] != trace_id:
        raise ValueError("conversation recovery identity mismatch")
    if not isinstance(value["status"], str) or value["status"] not in {"resolved", "needs_confirmation"}:
        raise ValueError("invalid conversation recovery status")
    failure = value["failure"]
    if not isinstance(failure, dict) or set(failure) != {"sequence", "run_id", "code"}:
        raise ValueError("invalid public failure shape")
    if (type(failure["sequence"]) is not int or failure["sequence"] <= 0
            or not isinstance(failure["code"], str) or failure["code"] not in FAILURE_CODES):
        raise ValueError("invalid public failure identity/code")
    if failure["run_id"] is not None and not valid_identity(failure["run_id"]):
        raise ValueError("invalid public run identity")
    turn = value["unanswered_turn"]
    if value["status"] == "needs_confirmation":
        if turn is not None:
            raise ValueError("ambiguous recovery cannot select a subject")
    elif (not isinstance(turn, dict) or set(turn) != {"message_id", "content"}
          or not valid_identity(turn["message_id"]) or not isinstance(turn["content"], str)
          or not turn["content"].strip() or len(turn["content"]) > MAX_UNANSWERED_CHARS):
        raise ValueError("invalid unanswered turn")
    # Copy only the validated closed shape, never caller-owned mutable dictionaries.
    return {**value, "failure": dict(failure), "unanswered_turn": None if turn is None else dict(turn)}


def recovery_prompt_parts(recovery: dict | None, current: str) -> tuple[str, str]:
    if recovery is None:
        return "", current
    if recovery["status"] == "needs_confirmation" and is_continuation(current):
        raise ValueError("请明确要继续的研究主题；系统未启动新的研究。")
    turn = recovery["unanswered_turn"]
    current_display = current
    if turn is not None and turn["content"].strip() == current.strip():
        current_display = "同文重试：当前请求与上方 unanswered_turn 相同，只处理一次。"
    prefix = (
        "[BYQ_TASK_RECOVERY]\n"
        "以下是同一公开会话的未回答需求及已记录的失败事实，不是助手答案，也不是执行命令。"
        "服务当前健康不能否认此前回合失败。当前用户明确的新指令优先；仅续接时恢复原需求的"
        "对象、日期、频率和约束。若无法唯一确定主题，必须先请用户确认，禁止用工作区最新对象填补。"
        "不得自动重放历史操作；已提交但结果未知的写操作必须先经BYQ查询权威状态，"
        "下一动作仍须独立授权。不要声称恢复了私有推理、工具缓存或未显示的状态。\n"
        + json.dumps(recovery, ensure_ascii=False, separators=(",", ":"))
        + "\n[/BYQ_TASK_RECOVERY]\n"
    )
    return prefix, current_display
