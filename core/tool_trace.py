#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Structured trace logging helpers for tool-calling requests.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

TRACE_TEXT_LIMIT = 600
TRACE_LIST_LIMIT = 12

trace_logger = logging.getLogger("tool_trace")


def truncate_text(value: Any, limit: int = TRACE_TEXT_LIMIT) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= limit:
        return value
    return value[:limit] + f"...<trimmed {len(value) - limit} chars>"


def _safe_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return truncate_text(value)
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_safe_jsonable(v) for v in value[:TRACE_LIST_LIMIT]]
        if len(value) > TRACE_LIST_LIMIT:
            items.append({"truncated_items": len(value) - TRACE_LIST_LIMIT})
        return items
    return repr(value)


def _get(mapping: Dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(mapping, dict) and name in mapping:
            return mapping[name]
    return default


def summarize_tool_definition(tool: Dict[str, Any]) -> Dict[str, Any]:
    function = tool.get("function", {}) if isinstance(tool, dict) else {}
    parameters = function.get("parameters") or {}
    properties = parameters.get("properties") or {}
    return {
        "type": tool.get("type"),
        "name": function.get("name"),
        "description": truncate_text(function.get("description")),
        "parameter_keys": list(properties.keys())[:TRACE_LIST_LIMIT],
        "required": parameters.get("required") or [],
    }


def summarize_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        arguments = json.dumps(_safe_jsonable(arguments), ensure_ascii=False)
    return {
        "id": tool_call.get("id"),
        "type": tool_call.get("type"),
        "name": function.get("name"),
        "arguments": truncate_text(arguments),
    }


def summarize_message(message: Dict[str, Any]) -> Dict[str, Any]:
    content = message.get("content")
    if isinstance(content, list):
        content_summary = [_safe_jsonable(item) for item in content[:TRACE_LIST_LIMIT]]
    else:
        content_summary = truncate_text(content)

    summary = {
        "role": message.get("role"),
        "content": content_summary,
    }
    if message.get("tool_call_id"):
        summary["tool_call_id"] = message.get("tool_call_id")
    if message.get("tool_calls"):
        summary["tool_calls"] = [summarize_tool_call(tc) for tc in message.get("tool_calls", [])[:TRACE_LIST_LIMIT]]
    return summary


def summarize_tool_result(tool_result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tool_call_id": tool_result.get("tool_call_id"),
        "content": truncate_text(tool_result.get("content")),
    }


def should_trace_request(messages: Iterable[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> bool:
    if tools:
        return True
    for message in messages:
        if message.get("role") == "tool":
            return True
        if message.get("role") == "assistant" and message.get("tool_calls"):
            return True
    return False


def summarize_openai_request(
    *,
    model: str,
    stream: bool,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Any = None,
    disable_warp_tools: Optional[bool] = None,
    reasoning_effort: Optional[str] = None,
    effective_model: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "model": model,
        "effective_model": effective_model or model,
        "stream": stream,
        "disable_warp_tools": disable_warp_tools,
        "reasoning_effort": reasoning_effort,
        "tool_choice": _safe_jsonable(tool_choice),
        "messages": [summarize_message(message) for message in messages[:TRACE_LIST_LIMIT]],
        "tool_count": len(tools or []),
        "tools": [summarize_tool_definition(tool) for tool in (tools or [])[:TRACE_LIST_LIMIT]],
    }


def summarize_openai_response(response: Dict[str, Any]) -> Dict[str, Any]:
    choices = []
    for choice in response.get("choices", [])[:TRACE_LIST_LIMIT]:
        message = choice.get("message", {})
        choices.append(
            {
                "index": choice.get("index"),
                "finish_reason": choice.get("finish_reason"),
                "message": {
                    "role": message.get("role"),
                    "content": truncate_text(message.get("content")),
                    "reasoning": truncate_text(message.get("reasoning") or message.get("reasoning_content")),
                    "tool_calls": [summarize_tool_call(tc) for tc in message.get("tool_calls", [])[:TRACE_LIST_LIMIT]],
                },
            }
        )
    return {
        "id": response.get("id"),
        "model": response.get("model"),
        "choices": choices,
        "usage": _safe_jsonable(response.get("usage")),
    }


def summarize_stream_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    choices = []
    for choice in chunk.get("choices", [])[:TRACE_LIST_LIMIT]:
        delta = choice.get("delta", {})
        choices.append(
            {
                "index": choice.get("index"),
                "finish_reason": choice.get("finish_reason"),
                "delta": {
                    "role": delta.get("role"),
                    "content": truncate_text(delta.get("content")),
                    "reasoning": truncate_text(delta.get("reasoning") or delta.get("reasoning_content")),
                    "tool_calls": [summarize_tool_call(tc) for tc in delta.get("tool_calls", [])[:TRACE_LIST_LIMIT]],
                },
            }
        )
    return {
        "id": chunk.get("id"),
        "model": chunk.get("model"),
        "choices": choices,
    }


def summarize_warp_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"tool_call_id": tool_call.get("tool_call_id")}
    for key, value in tool_call.items():
        if key == "tool_call_id":
            continue
        summary["name"] = key
        summary["payload"] = _safe_jsonable(value)
        break
    return summary


def summarize_warp_message(message: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    if message.get("id"):
        summary["id"] = message.get("id")
    agent_output = _get(message, "agent_output", "agentOutput", default={}) or {}
    if agent_output:
        summary["agent_output"] = {
            "text": truncate_text(agent_output.get("text")),
            "reasoning": truncate_text(agent_output.get("reasoning")),
        }
    agent_reasoning = _get(message, "agent_reasoning", "agentReasoning", default={}) or {}
    if agent_reasoning:
        summary["agent_reasoning"] = {
            "reasoning": truncate_text(agent_reasoning.get("reasoning")),
            "finished_duration": _safe_jsonable(
                agent_reasoning.get("finished_duration") or agent_reasoning.get("finishedDuration")
            ),
        }
    tool_call = _get(message, "tool_call", "toolCall")
    if tool_call:
        summary["tool_call"] = summarize_warp_tool_call(tool_call)
    if message.get("role"):
        summary["role"] = message.get("role")
    return summary


def summarize_warp_event(event: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"keys": list(event.keys())}

    if "init" in event:
        init = event.get("init") or {}
        summary["init"] = {"conversation_id": init.get("conversation_id")}

    actions_data = _get(event, "client_actions", "clientActions")
    if actions_data:
        actions = _get(actions_data, "actions", "Actions", default=[]) or []
        action_summaries = []
        for action in actions[:TRACE_LIST_LIMIT]:
            if "add_messages_to_task" in action or "addMessagesToTask" in action:
                payload = _get(action, "add_messages_to_task", "addMessagesToTask", default={}) or {}
                messages = payload.get("messages", []) or []
                action_summaries.append(
                    {
                        "type": "add_messages_to_task",
                        "messages": [summarize_warp_message(message) for message in messages[:TRACE_LIST_LIMIT]],
                    }
                )
            elif "append_to_message_content" in action or "appendToMessageContent" in action:
                payload = _get(action, "append_to_message_content", "appendToMessageContent", default={}) or {}
                action_summaries.append(
                    {
                        "type": "append_to_message_content",
                        "message": summarize_warp_message(payload.get("message", {}) or {}),
                    }
                )
            elif "update_task_message" in action or "updateTaskMessage" in action:
                payload = _get(action, "update_task_message", "updateTaskMessage", default={}) or {}
                action_summaries.append(
                    {
                        "type": "update_task_message",
                        "message": summarize_warp_message(payload.get("message", {}) or {}),
                    }
                )
            elif "create_task" in action or "createTask" in action:
                payload = _get(action, "create_task", "createTask", default={}) or {}
                task = payload.get("task", {}) or {}
                action_summaries.append(
                    {
                        "type": "create_task",
                        "task_id": task.get("id"),
                        "messages": [summarize_warp_message(message) for message in (task.get("messages", []) or [])[:TRACE_LIST_LIMIT]],
                    }
                )
            elif "update_task_summary" in action or "updateTaskSummary" in action:
                payload = _get(action, "update_task_summary", "updateTaskSummary", default={}) or {}
                action_summaries.append(
                    {
                        "type": "update_task_summary",
                        "summary": truncate_text(payload.get("summary")),
                    }
                )
            else:
                action_summaries.append({"type": "unknown", "keys": list(action.keys())})
        summary["client_actions"] = action_summaries

    if "finished" in event:
        summary["finished"] = _safe_jsonable(event.get("finished"))

    return summary


def log_tool_trace(event_name: str, trace_id: str, **payload: Any) -> None:
    record = {"trace_id": trace_id, **_safe_jsonable(payload), "event": event_name}
    trace_logger.info(json.dumps(record, ensure_ascii=False))
