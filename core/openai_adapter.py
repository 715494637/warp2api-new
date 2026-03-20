#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI 格式适配器 - 在OpenAI格式和Warp格式之间转换
"""
import uuid
import time
from typing import AsyncGenerator, Dict, Any, List, Optional
import logging
import base64
from core.tool_trace import log_tool_trace, summarize_openai_response, summarize_stream_chunk
from core.tool_compat import normalize_tool_call, normalize_tool_name, normalize_tool_calls

logger = logging.getLogger(__name__)

# 尝试导入 warp2protobuf 的响应解析器
try:
    from warp2protobuf.warp.response import extract_openai_sse_deltas_from_response
    USE_WARP_PARSER = True
    logger.info("Using warp2protobuf.warp.response parser for tool call support")
except ImportError:
    USE_WARP_PARSER = False
    logger.warning("Could not import warp2protobuf.warp.response, tool calls may not work")


class OpenAIAdapter:
    @staticmethod
    def _add_reasoning_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mirror reasoning text to multiple common compatibility keys.
        """
        if not payload:
            return payload

        reasoning = payload.get("reasoning")
        reasoning_content = payload.get("reasoning_content")

        if reasoning and not reasoning_content:
            payload["reasoning_content"] = reasoning
        elif reasoning_content and not reasoning:
            payload["reasoning"] = reasoning_content

        return payload

    @staticmethod
    def _has_emittable_delta(delta_content: Dict[str, Any]) -> bool:
        return bool(
            delta_content.get("content")
            or delta_content.get("tool_calls")
            or delta_content.get("reasoning")
            or delta_content.get("reasoning_content")
        )
    """OpenAI格式适配器"""
    
    @staticmethod
    def _log_trace(trace_id: Optional[str], event_name: str, **payload: Any) -> None:
        if not trace_id:
            return
        log_tool_trace(event_name, trace_id, **payload)

    @staticmethod
    def _serialize_stream_chunk(chunk: Dict[str, Any], trace_id: Optional[str] = None) -> str:
        OpenAIAdapter._log_trace(trace_id, "proxy_stream_out", chunk=summarize_stream_chunk(chunk))
        return f"data: {OpenAIAdapter._json_dumps(chunk)}\n\n"

    @staticmethod
    def transform_mcp_tool_call(tool_call: dict) -> dict:
        """
        MCP Gateway: 将 call_mcp_tool 转换为实际的工具调用
        
        Args:
            tool_call: OpenAI 格式的工具调用
        
        Returns:
            转换后的工具调用（如果是 call_mcp_tool）或原始工具调用
        """
        if not tool_call:
            return tool_call
        
        function = tool_call.get("function", {})
        function_name = function.get("name", "")
        
        # 如果不是 call_mcp_tool，直接返回
        if function_name != "call_mcp_tool":
            return normalize_tool_call(tool_call)
        
        # 解析 call_mcp_tool 的参数
        try:
            import json
            arguments_str = function.get("arguments", "{}")
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
            
            # 提取实际的工具名称和参数
            actual_tool_name = normalize_tool_name(arguments.get("name", ""))
            actual_args = arguments.get("args", {})
            
            if not actual_tool_name:
                logger.warning(f"call_mcp_tool missing 'name' field: {arguments}")
                return tool_call
            
            # 如果 args 是列表（参数名列表），需要从某处获取实际值
            # 这里我们假设客户端会提供完整的参数对象
            if isinstance(actual_args, list):
                # args 是参数名列表，转换为空对象（客户端需要填充）
                actual_args = {arg: "" for arg in actual_args}
            
            # 构建新的工具调用
            transformed = {
                "id": tool_call.get("id", ""),
                "type": "function",
                "function": {
                    "name": actual_tool_name,
                    "arguments": json.dumps(actual_args, ensure_ascii=False)
                }
            }
            
            logger.info(f"[MCP Gateway] Transformed call_mcp_tool -> {actual_tool_name}")
            logger.debug(f"[MCP Gateway] Original args: {arguments}")
            logger.debug(f"[MCP Gateway] Transformed args: {actual_args}")
            
            return normalize_tool_call(transformed)
            
        except Exception as e:
            logger.error(f"[MCP Gateway] Failed to transform call_mcp_tool: {e}", exc_info=True)
            return normalize_tool_call(tool_call)
    
    @staticmethod
    def openai_to_warp_messages(openai_messages: List[dict]) -> str:
        """
        将OpenAI消息格式转换为Warp格式
        
        Args:
            openai_messages: OpenAI格式的消息列表
        
        Returns:
            用户消息文本（Warp只需要最后一条用户消息）
        """
        # 提取最后一条用户消息
        for msg in reversed(openai_messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    # 处理多模态内容
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    return "\n".join(text_parts)
        
        return ""
    
    @staticmethod
    async def warp_to_openai_stream(
        warp_stream: AsyncGenerator[dict, None],
        model: str,
        completion_id: str = None,
        trace_id: str = None,
    ) -> AsyncGenerator[str, None]:
        """
        将Warp SSE流转换为OpenAI SSE格式
        
        Args:
            warp_stream: Warp事件流
            model: 模型名称
            completion_id: 完成ID
        
        Yields:
            OpenAI格式的SSE事件字符串
        """
        if not completion_id:
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        
        created_ts = int(time.time())
        message_id = None
        task_id = None
        first_chunk_sent = False
        
        try:
            async for event in warp_stream:
                # 如果有 warp2protobuf 解析器且事件包含原始 payload，使用它来处理（支持工具调用）
                if USE_WARP_PARSER and "raw_payload" in event:
                    try:
                        payload = event["raw_payload"]
                        logger.debug(f"Using warp parser for event with raw_payload ({len(payload)} bytes)")
                        deltas = extract_openai_sse_deltas_from_response(payload)
                        logger.debug(f"Warp parser returned {len(deltas)} deltas")
                        
                        saw_finish = False
                        for delta in deltas:
                            # 添加必要的字段
                            delta["id"] = completion_id
                            delta["object"] = "chat.completion.chunk"
                            delta["created"] = created_ts
                            delta["model"] = model
                            
                            # 首次发送需要包含 role
                            if not first_chunk_sent:
                                choice = delta.get("choices", [{}])[0]
                                delta_content = choice.get("delta", {})
                                if OpenAIAdapter._has_emittable_delta(delta_content):
                                    first_chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": created_ts,
                                        "model": model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"role": "assistant"},
                                            "finish_reason": None
                                        }]
                                    }
                                    yield OpenAIAdapter._serialize_stream_chunk(first_chunk, trace_id)
                                    first_chunk_sent = True
                            
                            # MCP Gateway: 流式模式下也需要转换 call_mcp_tool
                            choices = delta.get("choices", [])
                            for choice in choices:
                                delta_content = choice.get("delta", {})
                                OpenAIAdapter._add_reasoning_fields(delta_content)
                                if "tool_calls" in delta_content:
                                    # 转换每个工具调用
                                    transformed_tool_calls = []
                                    for tc in delta_content["tool_calls"]:
                                        # 对于流式模式，工具调用可能是增量的
                                        # 只有当 function.name 完整时才尝试转换
                                        function = tc.get("function", {})
                                        if function.get("name") == "call_mcp_tool" and function.get("arguments"):
                                            # 尝试转换（可能参数还不完整）
                                            try:
                                                import json
                                                args_str = function.get("arguments", "{}")
                                                args = json.loads(args_str)
                                                actual_name = normalize_tool_name(args.get("name", ""))
                                                if actual_name:
                                                    # 转换成功
                                                    transformed_tc = OpenAIAdapter.transform_mcp_tool_call(tc)
                                                    transformed_tool_calls.append(transformed_tc)
                                                    logger.debug(f"[Stream] Transformed call_mcp_tool -> {actual_name}")
                                                else:
                                                    # 参数不完整，保持原样
                                                    transformed_tool_calls.append(normalize_tool_call(tc))
                                            except json.JSONDecodeError:
                                                # JSON 还不完整，保持原样
                                                transformed_tool_calls.append(normalize_tool_call(tc))
                                        else:
                                            # 不是 call_mcp_tool 或参数为空，保持原样
                                            transformed_tool_calls.append(normalize_tool_call(tc))
                                    
                                    # 替换为转换后的工具调用
                                    delta_content["tool_calls"] = normalize_tool_calls(transformed_tool_calls)
                            
                                if choice.get("finish_reason"):
                                    saw_finish = True

                            yield OpenAIAdapter._serialize_stream_chunk(delta, trace_id)
                        
                        if saw_finish:
                            OpenAIAdapter._log_trace(trace_id, "proxy_stream_done")
                            yield "data: [DONE]\n\n"
                            return

                        continue
                    except Exception as e:
                        logger.warning(f"Failed to use warp parser: {e}, falling back to simple parser")
                
                # 处理init事件
                if "init" in event:
                    init_data = event["init"]
                    logger.debug(f"Stream init: conversation_id={init_data.get('conversation_id')}")
                    continue
                
                # 回退到简单解析器（不支持工具调用）
                if "client_actions" in event or "clientActions" in event:
                    actions_data = event.get("client_actions") or event.get("clientActions")
                    actions = actions_data.get("actions") or actions_data.get("Actions") or []
                    
                    for action in actions:
                        # 创建任务
                        if "create_task" in action or "createTask" in action:
                            task_data = action.get("create_task") or action.get("createTask")
                            task = task_data.get("task", {})
                            task_id = task.get("id")
                            logger.debug(f"Task created: {task_id}")
                        
                        # 添加消息（可能包含第一个文本片段）
                        elif "add_messages_to_task" in action or "addMessagesToTask" in action:
                            msg_data = action.get("add_messages_to_task") or action.get("addMessagesToTask")
                            messages = msg_data.get("messages", [])
                            for msg in messages:
                                if not message_id:
                                    message_id = msg.get("id")
                                    logger.debug(f"Message added: {message_id}")
                                
                                # 检查消息中是否有 agent_output
                                agent_output = msg.get("agent_output") or msg.get("agentOutput", {})
                                agent_reasoning = msg.get("agent_reasoning") or msg.get("agentReasoning", {})
                                text_delta = agent_output.get("text", "")
                                reasoning_delta = agent_output.get("reasoning", "") or agent_reasoning.get("reasoning", "")
                                if text_delta or reasoning_delta:
                                    # 首次发送需要包含 role
                                    if not first_chunk_sent:
                                        first_chunk = {
                                            "id": completion_id,
                                            "object": "chat.completion.chunk",
                                            "created": created_ts,
                                            "model": model,
                                            "choices": [
                                                {
                                                    "index": 0,
                                                    "delta": {
                                                        "role": "assistant",
                                                        "content": ""
                                                    },
                                                    "finish_reason": None
                                                }
                                            ]
                                        }
                                        yield OpenAIAdapter._serialize_stream_chunk(first_chunk, trace_id)
                                        first_chunk_sent = True
                                    
                                    if text_delta:
                                        chunk = {
                                            "id": completion_id,
                                            "object": "chat.completion.chunk",
                                            "created": created_ts,
                                            "model": model,
                                            "choices": [
                                                {
                                                    "index": 0,
                                                    "delta": {
                                                        "content": text_delta
                                                    },
                                                    "finish_reason": None
                                                }
                                            ]
                                        }
                                        yield OpenAIAdapter._serialize_stream_chunk(chunk, trace_id)

                                    if reasoning_delta:
                                        chunk = {
                                            "id": completion_id,
                                            "object": "chat.completion.chunk",
                                            "created": created_ts,
                                            "model": model,
                                            "choices": [
                                                {
                                                    "index": 0,
                                                    "delta": OpenAIAdapter._add_reasoning_fields({
                                                        "reasoning": reasoning_delta
                                                    }),
                                                    "finish_reason": None
                                                }
                                            ]
                                        }
                                        yield OpenAIAdapter._serialize_stream_chunk(chunk, trace_id)
                        
                        # 追加内容（流式输出）
                        elif "append_to_message_content" in action or "appendToMessageContent" in action:
                            append_data = action.get("append_to_message_content") or action.get("appendToMessageContent")
                            # 文本在 message.agent_output.text 中
                            message_data = append_data.get("message", {})
                            agent_output = message_data.get("agent_output") or message_data.get("agentOutput", {})
                            agent_reasoning = message_data.get("agent_reasoning") or message_data.get("agentReasoning", {})
                            text_delta = agent_output.get("text", "")
                            reasoning_delta = agent_output.get("reasoning", "") or agent_reasoning.get("reasoning", "")
                            
                            if text_delta or reasoning_delta:
                                # 首次发送需要包含 role
                                if not first_chunk_sent:
                                    first_chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": created_ts,
                                        "model": model,
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {
                                                    "role": "assistant",
                                                    "content": ""
                                                },
                                                "finish_reason": None
                                            }
                                        ]
                                    }
                                    yield OpenAIAdapter._serialize_stream_chunk(first_chunk, trace_id)
                                    first_chunk_sent = True
                                
                                # 生成OpenAI格式的chunk
                                if text_delta:
                                    chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": created_ts,
                                        "model": model,
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {
                                                    "content": text_delta
                                                },
                                                "finish_reason": None
                                            }
                                        ]
                                    }
                                    yield OpenAIAdapter._serialize_stream_chunk(chunk, trace_id)

                                if reasoning_delta:
                                    chunk = {
                                        "id": completion_id,
                                        "object": "chat.completion.chunk",
                                        "created": created_ts,
                                        "model": model,
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": OpenAIAdapter._add_reasoning_fields({
                                                    "reasoning": reasoning_delta
                                                }),
                                                "finish_reason": None
                                            }
                                        ]
                                    }
                                    yield OpenAIAdapter._serialize_stream_chunk(chunk, trace_id)
                
                # 处理finished事件
                elif "finished" in event:
                    finished_data = event["finished"]
                    reason_data = finished_data.get("reason", {})
                    
                    # 确定finish_reason
                    finish_reason = "stop"
                    if "max_token_limit" in reason_data or "maxTokenLimit" in reason_data:
                        finish_reason = "length"
                    elif "quota_limit" in reason_data or "quotaLimit" in reason_data:
                        finish_reason = "stop"  # 配额用尽也算正常结束
                    
                    # 发送最后一个chunk
                    final_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": finish_reason
                            }
                        ]
                    }
                    
                    yield OpenAIAdapter._serialize_stream_chunk(final_chunk, trace_id)
                    
                    # 发送[DONE]
                    OpenAIAdapter._log_trace(trace_id, "proxy_stream_done")
                    yield "data: [DONE]\n\n"
                    
                    logger.debug(f"Stream finished: {finish_reason}")
                    return
        
        except Exception as e:
            logger.error(f"Error in warp_to_openai_stream: {e}")
            # 发送错误信息
            error_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }
                ]
            }
            OpenAIAdapter._log_trace(
                trace_id,
                "proxy_error",
                stage="warp_to_openai_stream",
                error_type=type(e).__name__,
                error=str(e),
            )
            yield OpenAIAdapter._serialize_stream_chunk(error_chunk, trace_id)
            yield "data: [DONE]\n\n"
    
    @staticmethod
    async def warp_to_openai_response(
        warp_stream: AsyncGenerator[dict, None],
        model: str,
        completion_id: str = None,
        trace_id: str = None,
    ) -> dict:
        """
        将Warp流转换为OpenAI非流式响应
        
        Args:
            warp_stream: Warp事件流
            model: 模型名称
            completion_id: 完成ID
        
        Returns:
            OpenAI格式的响应字典
        """
        if not completion_id:
            completion_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        
        created_ts = int(time.time())
        content_parts = []
        reasoning_parts = []
        tool_calls = []
        finish_reason = "stop"
        prompt_tokens = 0
        completion_tokens = 0
        
        try:
            event_count = 0
            async for event in warp_stream:
                event_count += 1
                logger.debug(f"Processing event #{event_count}: {list(event.keys())}")

                # 先从 finished 事件提取 usage/finish_reason。
                # 即使后续 raw parser 成功并 continue，也不能丢掉这些元数据。
                if "finished" in event:
                    finished_data = event["finished"]

                    token_usage = finished_data.get("token_usage") or finished_data.get("tokenUsage") or []
                    if token_usage:
                        for usage in token_usage:
                            prompt_tokens += usage.get("total_input") or usage.get("totalInput") or 0
                            completion_tokens += usage.get("output") or 0

                    reason_data = finished_data.get("reason", {})
                    if "max_token_limit" in reason_data or "maxTokenLimit" in reason_data:
                        finish_reason = "length"
                    elif tool_calls:
                        finish_reason = "tool_calls"
                    else:
                        finish_reason = "stop"
                
                # 使用 warp parser 解析事件（与流式模式相同）
                if USE_WARP_PARSER and "raw_payload" in event:
                    try:
                        payload = event["raw_payload"]
                        logger.debug(f"[Non-streaming] Using warp parser for event with raw_payload ({len(payload)} bytes)")
                        deltas = extract_openai_sse_deltas_from_response(payload)
                        logger.debug(f"[Non-streaming] Warp parser returned {len(deltas)} deltas")
                        
                        for delta in deltas:
                            choices = delta.get("choices", [])
                            if choices:
                                choice = choices[0]
                                delta_content = choice.get("delta", {})
                                
                                # 提取文本内容
                                if "content" in delta_content:
                                    content_parts.append(delta_content["content"])

                                reasoning_text = delta_content.get("reasoning") or delta_content.get("reasoning_content")
                                if reasoning_text:
                                    reasoning_parts.append(reasoning_text)
                                
                                # 提取工具调用
                                if "tool_calls" in delta_content:
                                    for tc_delta in delta_content["tool_calls"]:
                                        # 累积工具调用（可能分多个 delta）
                                        tc_index = tc_delta.get("index", 0)
                                        
                                        # 确保 tool_calls 列表足够长
                                        while len(tool_calls) <= tc_index:
                                            tool_calls.append({
                                                "id": "",
                                                "type": "function",
                                                "function": {
                                                    "name": "",
                                                    "arguments": ""
                                                }
                                            })
                                        
                                        # 累积字段
                                        if "id" in tc_delta:
                                            tool_calls[tc_index]["id"] = tc_delta["id"]
                                        if "type" in tc_delta:
                                            tool_calls[tc_index]["type"] = tc_delta["type"]
                                        if "function" in tc_delta:
                                            func_delta = tc_delta["function"]
                                            if "name" in func_delta:
                                                tool_calls[tc_index]["function"]["name"] += func_delta["name"]
                                            if "arguments" in func_delta:
                                                tool_calls[tc_index]["function"]["arguments"] += func_delta["arguments"]
                                
                                # 提取 finish_reason
                                if choice.get("finish_reason"):
                                    finish_reason = choice["finish_reason"]
                        
                        if deltas:
                            continue  # 已经处理，跳过后续的回退逻辑
                    except Exception as e:
                        logger.debug(f"Could not parse with warp parser: {e}", exc_info=True)
                
                # 提取文本内容
                if "client_actions" in event or "clientActions" in event:
                    actions_data = event.get("client_actions") or event.get("clientActions")
                    actions = actions_data.get("actions") or actions_data.get("Actions") or []
                    
                    logger.debug(f"Found {len(actions)} actions in event")
                    
                    for action in actions:
                        logger.debug(f"Action keys: {list(action.keys())}")
                        
                        # 从 add_messages_to_task 中提取文本
                        if "add_messages_to_task" in action or "addMessagesToTask" in action:
                            msg_data = action.get("add_messages_to_task") or action.get("addMessagesToTask")
                            messages = msg_data.get("messages", [])
                            for msg in messages:
                                agent_output = msg.get("agent_output") or msg.get("agentOutput", {})
                                agent_reasoning = msg.get("agent_reasoning") or msg.get("agentReasoning", {})
                                text_delta = agent_output.get("text", "")
                                reasoning_delta = agent_output.get("reasoning", "") or agent_reasoning.get("reasoning", "")
                                if text_delta:
                                    logger.debug(f"Adding text from add_messages: {text_delta[:50]}...")
                                    content_parts.append(text_delta)
                                if reasoning_delta:
                                    logger.debug(f"Adding reasoning from add_messages: {reasoning_delta[:50]}...")
                                    reasoning_parts.append(reasoning_delta)
                        
                        # 从 append_to_message_content 中提取文本
                        elif "append_to_message_content" in action or "appendToMessageContent" in action:
                            append_data = action.get("append_to_message_content") or action.get("appendToMessageContent")
                            # 文本在 message.agent_output.text 中
                            message_data = append_data.get("message", {})
                            agent_output = message_data.get("agent_output") or message_data.get("agentOutput", {})
                            agent_reasoning = message_data.get("agent_reasoning") or message_data.get("agentReasoning", {})
                            text_delta = agent_output.get("text", "")
                            reasoning_delta = agent_output.get("reasoning", "") or agent_reasoning.get("reasoning", "")
                            if text_delta:
                                logger.debug(f"Appending text: {text_delta[:50]}...")
                                content_parts.append(text_delta)
                            if reasoning_delta:
                                logger.debug(f"Appending reasoning: {reasoning_delta[:50]}...")
                                reasoning_parts.append(reasoning_delta)
                
        except Exception as e:
            OpenAIAdapter._log_trace(
                trace_id,
                "proxy_error",
                stage="warp_to_openai_response",
                error_type=type(e).__name__,
                error=str(e),
            )
            logger.error(f"Error in warp_to_openai_response: {e}")
            raise  # 重新抛出异常以便上层重试
        
        # 组装完整内容
        full_content = "".join(content_parts)
        full_reasoning = "".join(reasoning_parts)

        # OpenAI 兼容语义：一旦 assistant 消息里包含 tool_calls，
        # finish_reason 应返回 tool_calls，而不是 stop。
        if tool_calls and finish_reason == "stop":
            finish_reason = "tool_calls"
        
        # 构建消息对象
        message = {
            "role": "assistant",
            "content": full_content
        }
        if full_reasoning:
            message["reasoning"] = full_reasoning
            message["reasoning_content"] = full_reasoning
        
        # 如果有工具调用，添加到消息中
        if tool_calls:
            # MCP Gateway: 转换 call_mcp_tool 为实际工具调用
            transformed_tool_calls = [
                OpenAIAdapter.transform_mcp_tool_call(tc) for tc in tool_calls
            ]
            message["tool_calls"] = transformed_tool_calls
            logger.info(f"Non-streaming response includes {len(transformed_tool_calls)} tool calls")
        
        # 构建OpenAI响应
        response = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            }
        }
        
        OpenAIAdapter._log_trace(trace_id, "proxy_response_out", response=summarize_openai_response(response))
        return response
    
    @staticmethod
    def _json_dumps(obj: dict) -> str:
        """JSON序列化（紧凑格式）"""
        import json
        return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
