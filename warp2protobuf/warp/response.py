#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Warp API response parsing

Handles parsing of protobuf responses and extraction of OpenAI-compatible content.
"""
import json
from typing import Optional, Dict, List, Any

from google.protobuf.json_format import MessageToDict

from ..core.logging import logger
from ..core.protobuf import ensure_proto_runtime, msg_cls
from core.tool_compat import normalize_tool_call, normalize_tool_name, should_defer_tool_call


_REASONING_BLOCK_CACHE: Dict[str, str] = {}
_MAX_REASONING_BLOCK_CACHE = 2048


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}

    if hasattr(value, "ListFields"):
        try:
            return MessageToDict(value, preserving_proto_field_name=True)
        except Exception:
            converted: Dict[str, Any] = {}
            for field, field_value in value.ListFields():
                converted[field.name] = _to_jsonable(field_value)
            return converted

    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]

    return str(value)


def _extract_openai_tool_call(tool_call: Any, fallback_id: str) -> tuple[Optional[Dict[str, Any]], bool]:
    tool_call_id = tool_call.tool_call_id if tool_call.tool_call_id else fallback_id
    tool_name = "unknown"
    tool_args: Dict[str, Any] = {}

    for field, value in tool_call.ListFields():
        if field.name == "tool_call_id":
            continue
        tool_name = field.name

        if tool_name == "server":
            logger.debug("Skipping internal 'server' event")
            return None, False

        if hasattr(value, "ListFields"):
            if tool_name == "call_mcp_tool":
                actual_tool_name = None
                for tool_field, tool_value in value.ListFields():
                    if tool_field.name == "name":
                        actual_tool_name = tool_value
                    elif tool_field.name == "args":
                        tool_args = _to_jsonable(tool_value)
                if actual_tool_name:
                    tool_name = normalize_tool_name(actual_tool_name)
            else:
                converted_args = _to_jsonable(value)
                if isinstance(converted_args, dict):
                    tool_args = converted_args
                else:
                    tool_args = {"value": converted_args}
        break

    tool_name = normalize_tool_name(tool_name)
    openai_tool_call = normalize_tool_call(
        {
            "id": tool_call_id,
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(tool_args, ensure_ascii=False),
            },
        }
    )
    return openai_tool_call, should_defer_tool_call(tool_name, tool_args)


def _upsert_tool_call(tool_calls: List[Dict[str, Any]], tool_call: Dict[str, Any]) -> None:
    for index, existing in enumerate(tool_calls):
        if existing.get("id") == tool_call.get("id"):
            tool_calls[index] = tool_call
            return
    tool_calls.append(tool_call)


def _append_reasoning(result: Dict[str, Any], reasoning: str) -> None:
    if not reasoning:
        return
    if "reasoning" not in result:
        result["reasoning"] = ""
    result["reasoning"] += reasoning


def _trim_reasoning_block_cache() -> None:
    while len(_REASONING_BLOCK_CACHE) > _MAX_REASONING_BLOCK_CACHE:
        _REASONING_BLOCK_CACHE.pop(next(iter(_REASONING_BLOCK_CACHE)))


def _extract_reasoning_block(message: Any) -> Optional[str]:
    if not hasattr(message, "HasField") or not message.HasField("agent_reasoning"):
        return None

    reasoning = message.agent_reasoning.reasoning
    if not reasoning:
        return None

    message_id = getattr(message, "id", "") or f"anonymous:{hash(reasoning)}"
    previous = _REASONING_BLOCK_CACHE.get(message_id)
    _REASONING_BLOCK_CACHE[message_id] = reasoning
    _trim_reasoning_block_cache()

    if previous == reasoning:
        return None
    if previous:
        return f"\n\n{reasoning}"
    return reasoning


def _append_agent_output(result: Dict[str, Any], message: Any) -> None:
    if not message.HasField("agent_output"):
        return

    agent_output = message.agent_output
    if agent_output.text:
        result["content"] += agent_output.text
    _append_reasoning(result, agent_output.reasoning)


def _append_tool_call(result: Dict[str, Any], message: Any, fallback_id: str) -> None:
    if not message.HasField("tool_call"):
        return

    openai_tool_call, should_defer = _extract_openai_tool_call(message.tool_call, fallback_id)
    if openai_tool_call and not should_defer:
        _upsert_tool_call(result["tool_calls"], openai_tool_call)


def extract_openai_content_from_response(payload: bytes) -> dict:
    """
    Extract OpenAI-compatible content from Warp API response payload.
    """
    if not payload:
        logger.debug("extract_openai_content_from_response: payload is empty")
        return {"content": None, "tool_calls": [], "finish_reason": None, "metadata": {}}

    logger.debug(f"extract_openai_content_from_response: processing payload of {len(payload)} bytes")
    logger.debug(f"extract_openai_content_from_response: complete payload hex: {payload.hex()}")

    try:
        ensure_proto_runtime()
        ResponseEvent = msg_cls("warp.multi_agent.v1.ResponseEvent")
        response = ResponseEvent()
        response.ParseFromString(payload)

        result = {"content": "", "tool_calls": [], "finish_reason": None, "metadata": {}}

        if response.HasField("client_actions"):
            for i, action in enumerate(response.client_actions.actions):
                if action.HasField("append_to_message_content"):
                    message = action.append_to_message_content.message
                    _append_agent_output(result, message)
                    _append_tool_call(result, message, f"call_{i}")

                elif action.HasField("add_messages_to_task"):
                    for j, msg in enumerate(action.add_messages_to_task.messages):
                        _append_agent_output(result, msg)
                        _append_tool_call(result, msg, f"call_{i}_{j}")

                elif action.HasField("update_task_message"):
                    update = action.update_task_message
                    message = update.message
                    mask_paths = set(update.mask.paths)
                    if "server_message_data" in mask_paths or "agent_reasoning.finished_duration" in mask_paths:
                        _append_reasoning(result, _extract_reasoning_block(message) or "")
                    _append_tool_call(result, message, f"call_{i}")

                elif action.HasField("create_task"):
                    task = action.create_task.task
                    for msg in task.messages:
                        _append_agent_output(result, msg)

                elif action.HasField("update_task_summary"):
                    summary = action.update_task_summary.summary
                    if summary:
                        result["content"] += summary

        if response.HasField("finished"):
            result["finish_reason"] = "stop"

        result["metadata"] = {
            "response_fields": [field.name for field, _ in response.ListFields()],
            "has_client_actions": response.HasField("client_actions"),
            "payload_size": len(payload),
        }
        return result
    except Exception as e:
        logger.error(f"extract_openai_content_from_response: exception occurred: {e}")
        import traceback
        logger.error(f"extract_openai_content_from_response: traceback: {traceback.format_exc()}")
        return {"content": None, "tool_calls": [], "finish_reason": "error", "metadata": {"error": str(e)}}


def extract_text_from_response(payload: bytes) -> Optional[str]:
    result = extract_openai_content_from_response(payload)
    return result["content"] if result["content"] else None


def _append_text_delta(deltas: List[Dict[str, Any]], text: str) -> None:
    if text:
        deltas.append({"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]})


def _append_reasoning_delta(deltas: List[Dict[str, Any]], reasoning: Optional[str]) -> None:
    if reasoning:
        deltas.append({"choices": [{"index": 0, "delta": {"reasoning": reasoning}, "finish_reason": None}]})


def _append_tool_call_deltas(deltas: List[Dict[str, Any]], message: Any, fallback_id: str, include_role: bool = True) -> None:
    if not message.HasField("tool_call"):
        return

    openai_tool_call, should_defer = _extract_openai_tool_call(message.tool_call, fallback_id)
    if openai_tool_call and not should_defer:
        if include_role:
            deltas.append({"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
        deltas.append({"choices": [{"index": 0, "delta": {"tool_calls": [openai_tool_call]}, "finish_reason": None}]})


def extract_openai_sse_deltas_from_response(payload: bytes) -> List[Dict[str, Any]]:
    if not payload:
        return []

    try:
        ensure_proto_runtime()
        ResponseEvent = msg_cls("warp.multi_agent.v1.ResponseEvent")
        response = ResponseEvent()
        response.ParseFromString(payload)
        deltas: List[Dict[str, Any]] = []

        if response.HasField("client_actions"):
            for i, action in enumerate(response.client_actions.actions):
                if action.HasField("append_to_message_content"):
                    message = action.append_to_message_content.message
                    if message.HasField("agent_output"):
                        agent_output = message.agent_output
                        _append_text_delta(deltas, agent_output.text)
                        _append_reasoning_delta(deltas, agent_output.reasoning)
                    _append_tool_call_deltas(deltas, message, f"call_{i}")

                elif action.HasField("add_messages_to_task"):
                    for j, msg in enumerate(action.add_messages_to_task.messages):
                        if msg.HasField("agent_output"):
                            _append_text_delta(deltas, msg.agent_output.text)
                            _append_reasoning_delta(deltas, msg.agent_output.reasoning)
                        _append_tool_call_deltas(deltas, msg, f"call_{i}_{j}", include_role=(j == 0))

                elif action.HasField("update_task_message"):
                    update = action.update_task_message
                    message = update.message
                    mask_paths = set(update.mask.paths)
                    if "server_message_data" in mask_paths or "agent_reasoning.finished_duration" in mask_paths:
                        _append_reasoning_delta(deltas, _extract_reasoning_block(message))
                    elif not message.HasField("tool_call"):
                        logger.debug("Skipping update_task_message snapshot in SSE delta parser")

                    if message.HasField("tool_call"):
                        _append_tool_call_deltas(deltas, message, f"call_{i}")

                elif action.HasField("create_task"):
                    logger.debug("Skipping create_task snapshot in SSE delta parser")

                elif action.HasField("update_task_summary"):
                    logger.debug("Skipping update_task_summary snapshot in SSE delta parser")

        if response.HasField("finished"):
            deltas.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})

        return deltas
    except Exception as e:
        logger.error(f"extract_openai_sse_deltas_from_response: exception occurred: {e}")
        import traceback
        logger.error(f"extract_openai_sse_deltas_from_response: traceback: {traceback.format_exc()}")
        return []
