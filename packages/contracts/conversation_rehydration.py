"""Bounded Product conversation context used to rehydrate a fresh DSH process."""

from __future__ import annotations

import json
from typing import Literal, cast

from typing_extensions import TypedDict


CONVERSATION_REHYDRATION_VERSION = "conversation-rehydration.v1"
MAX_REHYDRATION_MESSAGES = 20
MAX_REHYDRATION_MESSAGE_CHARS = 6_000
MAX_REHYDRATION_TOTAL_CHARS = 24_000


class ConversationContextMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


def normalize_conversation_context(value: object) -> list[ConversationContextMessage]:
    """Validate the internal, user-visible transcript boundary."""

    if not isinstance(value, list):
        raise ValueError("conversation context must be a list")
    if len(value) > MAX_REHYDRATION_MESSAGES:
        raise ValueError("conversation context has too many messages")
    normalized: list[ConversationContextMessage] = []
    total = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise ValueError("conversation context message has an invalid field set")
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            raise ValueError("conversation context role is not supported")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("conversation context content must be non-empty text")
        if len(content) > MAX_REHYDRATION_MESSAGE_CHARS:
            raise ValueError("conversation context message exceeds the character limit")
        total += len(content)
        if total > MAX_REHYDRATION_TOTAL_CHARS:
            raise ValueError("conversation context exceeds the total character limit")
        normalized.append({"role": cast(Literal["user", "assistant"], role), "content": content})
    return normalized


def rehydrated_prompt(messages: list[ConversationContextMessage], current: str) -> str:
    """Compose one bounded prompt without pretending to restore private DSH state."""

    if not messages:
        return current
    transcript = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return (
        "[BYQ_CONVERSATION_REHYDRATION]\n"
        f"schema_version={CONVERSATION_REHYDRATION_VERSION}\n"
        "以下 JSON 是当前用户在同一 BeyondQuant 对话中已经完成并持久化的公开历史。"
        "仅用它延续对话语义；当前用户消息优先。不要重复执行历史操作，也不要声称恢复了未显示的内部状态。\n"
        f"{transcript}\n"
        "[/BYQ_CONVERSATION_REHYDRATION]\n"
        "[CURRENT_USER_MESSAGE]\n"
        f"{current}\n"
        "[/CURRENT_USER_MESSAGE]"
    )
