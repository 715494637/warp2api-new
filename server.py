#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Warp2OpenAI 简化版服务器
"""
import asyncio
import logging
import sys
import os
import json
import uuid
from pathlib import Path
from typing import Optional, List, Union, Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, ConfigDict
import uvicorn

# 添加当前目录到路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from core.account_manager import AccountManager, Account, StrategyType, load_accounts_from_directory, NoAvailableAccountError
from core.warp_client import WarpClient
from core.openai_adapter import OpenAIAdapter
from core.anthropic_adapter import AnthropicAdapter
from core.tool_trace import (
    log_tool_trace,
    should_trace_request,
    summarize_openai_request,
)
from warp2protobuf.config.models import get_all_unique_models, resolve_request_model

# 日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
LOG_DIR = current_dir / "logs"
LOG_FILE = LOG_DIR / "warp_api.log"
TOOL_TRACE_FILE = LOG_DIR / "tool_trace.log"


def setup_logging(level_str: str = "INFO"):
    """
    配置日志：同时输出到控制台和文件
    
    Args:
        level_str: 日志级别 (DEBUG, INFO, WARNING, ERROR)
    """
    level = getattr(logging, level_str.upper(), logging.INFO)
    
    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 清除已有的 handlers（避免重复添加）
    root_logger.handlers.clear()
    
    # 创建格式器
    formatter = logging.Formatter(LOG_FORMAT)
    
    # 控制台 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 文件 Handler（追加模式）
    file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    tool_trace_logger = logging.getLogger("tool_trace")
    tool_trace_logger.setLevel(logging.INFO)
    tool_trace_logger.handlers.clear()
    tool_trace_handler = logging.FileHandler(TOOL_TRACE_FILE, mode='a', encoding='utf-8')
    tool_trace_handler.setLevel(logging.INFO)
    tool_trace_handler.setFormatter(formatter)
    tool_trace_logger.addHandler(tool_trace_handler)
    tool_trace_logger.propagate = False
    
    # 同时设置 uvicorn 的日志级别
    for name in ['uvicorn', 'uvicorn.error', 'uvicorn.access']:
        uvi_logger = logging.getLogger(name)
        uvi_logger.setLevel(level)
        # uvicorn 日志也输出到文件
        uvi_logger.handlers.clear()
        uvi_logger.addHandler(console_handler)
        uvi_logger.addHandler(file_handler)
    
    # 设置 httpx 和 httpcore 的日志级别（减少噪音）
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    
    return root_logger


def _apply_log_level(level_str: str):
    """应用日志级别（兼容旧接口）"""
    setup_logging(level_str)


# 初始化日志
setup_logging("INFO")
logger = logging.getLogger("warp_api")

# 创建FastAPI应用
app = FastAPI(
    title="Warp2OpenAI Simplified",
    description="OpenAI-compatible API for Warp AI with multi-account support",
    version="1.0.0"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录（前端管理页面）
frontend_dir = current_dir / "frontend"
if frontend_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

# 全局变量
account_manager: Optional[AccountManager] = None
settings: dict = {}
accounts_config: dict = {}


# ==================== Pydantic 模型 ====================

class FunctionCall(BaseModel):
    """Function call in a message"""
    name: str
    arguments: str


class ToolCall(BaseModel):
    """Tool call in a message"""
    id: str
    type: str = "function"
    function: FunctionCall


class ChatMessage(BaseModel):
    """Chat message with OpenAI compatibility"""
    model_config = ConfigDict(extra='allow')  # 允许额外字段
    
    role: str
    content: Optional[Union[str, List[Any]]] = None  # 可以是字符串或多模态内容
    name: Optional[str] = None  # function/tool name
    tool_calls: Optional[List[ToolCall]] = None  # assistant's tool calls
    tool_call_id: Optional[str] = None  # for tool role messages
    
    @field_validator('content', mode='before')
    @classmethod
    def normalize_content(cls, v):
        """将 content 统一转换为字符串"""
        if v is None:
            return ""
        if isinstance(v, list):
            # 处理多模态内容格式 [{"type": "text", "text": "..."}]
            text_parts = []
            for part in v:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            return "\n".join(text_parts) if text_parts else ""
        return v


class FunctionDefinition(BaseModel):
    """Function definition for tools"""
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class Tool(BaseModel):
    """Tool definition"""
    type: str = "function"
    function: FunctionDefinition


class ResponseFormat(BaseModel):
    """Response format specification"""
    type: str = "text"  # "text" or "json_object"


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request"""
    model_config = ConfigDict(extra='allow')  # 允许额外字段
    
    model: str = "claude-4-sonnet"
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    reasoning_effort: Optional[str] = None
    
    # Tools / Function calling
    tools: Optional[List[Tool]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None  # "auto", "none", or specific tool
    
    # Other OpenAI parameters
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stop: Optional[Union[str, List[str]]] = None
    user: Optional[str] = None
    response_format: Optional[ResponseFormat] = None
    seed: Optional[int] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    n: Optional[int] = None


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 1234567890
    owned_by: str = "warp"


# ==================== Anthropic Pydantic 模型 ====================

class AnthropicContentBlock(BaseModel):
    """Anthropic content block"""
    model_config = ConfigDict(extra='allow')
    
    type: str  # "text", "image", "tool_use", "tool_result"
    text: Optional[str] = None
    # tool_use fields
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    # tool_result fields
    tool_use_id: Optional[str] = None
    content: Optional[Union[str, List[Any]]] = None
    is_error: Optional[bool] = None
    # image fields
    source: Optional[Dict[str, Any]] = None


class AnthropicMessage(BaseModel):
    """Anthropic message"""
    model_config = ConfigDict(extra='allow')
    
    role: str  # "user" or "assistant"
    content: Union[str, List[AnthropicContentBlock]]


class AnthropicToolDefinition(BaseModel):
    """Anthropic tool definition"""
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None


class AnthropicMessagesRequest(BaseModel):
    """Anthropic Messages API request"""
    model_config = ConfigDict(extra='allow')
    
    model: str
    messages: List[AnthropicMessage]
    max_tokens: int = 4096
    system: Optional[str] = None
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[List[str]] = None
    tools: Optional[List[AnthropicToolDefinition]] = None
    tool_choice: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


# ==================== API 端点 ====================

@app.get("/")
async def root():
    """根端点"""
    return {
        "name": "Warp2OpenAI Simplified",
        "version": "1.0.0",
        "endpoints": {
            "chat": "/v1/chat/completions",
            "anthropic": "/v1/messages",
            "models": "/v1/models",
            "health": "/health",
            "stats": "/stats",
            "admin": "/admin"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    if not account_manager:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "reason": "Account manager not initialized"}
        )
    
    available = len(account_manager.get_available_accounts())
    
    return {
        "status": "healthy" if available > 0 else "degraded",
        "available_accounts": available,
        "total_accounts": len(account_manager.accounts)
    }


@app.get("/v1/models")
async def list_models():
    """列出可用模型"""
    return {"object": "list", "data": get_all_unique_models()}


# ==================== 路由辅助函数 ====================

async def handle_chat_completion(request: ChatCompletionRequest):
    """聊天完成处理函数"""
    if not account_manager:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "Service not initialized", "type": "service_error", "code": 503}}
        )
    
    max_retries = 3  # 最多重试 3 次
    last_error = None
    
    for attempt in range(max_retries):
        account = None
        try:
            account = await account_manager.get_next_account()
            logger.info(f"[Attempt {attempt + 1}/{max_retries}] Using Warp account: {account.name} for model: {request.model}")
            
            client = account.get_warp_client()
            
            # 转换消息格式
            messages_list = []
            for msg in request.messages:
                msg_dict = {"role": msg.role, "content": msg.content}
                if msg.role == "tool" and msg.tool_call_id:
                    msg_dict["tool_call_id"] = msg.tool_call_id
                if msg.role == "assistant" and msg.tool_calls:
                    msg_dict["tool_calls"] = [tc.model_dump() if hasattr(tc, 'model_dump') else tc for tc in msg.tool_calls]
                messages_list.append(msg_dict)
            
            disable_warp_tools = settings.get("disable_warp_tools", True)
            tools = None
            if request.tools:
                tools = [tool.model_dump() if hasattr(tool, 'model_dump') else tool for tool in request.tools]
            
            warp_stream = client.chat_completion(
                messages=messages_list,
                model=request.model,
                stream=request.stream,
                disable_warp_tools=disable_warp_tools,
                tools=tools
            )
            
            if request.stream:
                return StreamingResponse(
                    OpenAIAdapter.warp_to_openai_stream(warp_stream, request.model),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    }
                )
            else:
                response = await OpenAIAdapter.warp_to_openai_response(warp_stream, request.model)
                return response
        
        except NoAvailableAccountError as e:
            logger.error(f"No available accounts: {e}")
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "No available accounts", "type": "service_unavailable", "code": 503}}
            )
        
        except HTTPException as e:
            # 如果是 403 或 429 错误，标记账户并重试
            if e.status_code == 403:
                logger.warning(f"Account returned 403, marking as blocked and retrying...")
                account.mark_blocked(403, "Blocked")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue  # 重试下一个账户
                else:
                    raise  # 最后一次尝试失败，抛出异常
            elif e.status_code == 429:
                logger.warning(f"Account returned 429, marking as rate limited and retrying...")
                account.mark_blocked(429, "Too Many Requests")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue  # 重试下一个账户
                else:
                    raise  # 最后一次尝试失败，抛出异常
            else:
                raise  # 其他 HTTP 错误直接抛出
        
        except Exception as e:
            # 检查是否是 403 相关错误
            error_str = str(e).lower()
            if "403" in error_str or "forbidden" in error_str or "unauthorized" in error_str:
                logger.warning(f"Account error (403-like): {e}, marking as blocked and retrying...")
                account.mark_blocked(403, "Blocked")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue  # 重试下一个账户
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    return JSONResponse(
                        status_code=500,
                        content={"error": {"message": f"All accounts failed: {str(e)}", "type": "server_error", "code": 500}}
                    )
            elif "429" in error_str or "too many" in error_str or "rate limit" in error_str:
                logger.warning(f"Account error (429-like): {e}, marking as rate limited and retrying...")
                account.mark_blocked(429, "Too Many Requests")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    return JSONResponse(
                        status_code=500,
                        content={"error": {"message": f"All accounts failed: {str(e)}", "type": "server_error", "code": 500}}
                    )
            elif "failed to prepare" in error_str:
                # 账户准备失败（token刷新或登录失败）
                # 不覆盖已有的状态码，因为 warp_client 已经标记了真实的错误状态
                logger.warning(f"Account prepare failed: {e}, retrying with next account...")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    return JSONResponse(
                        status_code=500,
                        content={"error": {"message": f"All accounts failed: {str(e)}", "type": "server_error", "code": 500}}
                    )
            else:
                # 其他错误直接抛出
                return JSONResponse(
                    status_code=500,
                    content={"error": {"message": str(e), "type": "er_error", "code": 500}}
                )
    
    # 如果所有重试都失败
    if last_error:
        logger.error(f"All {max_retries} attempts failed")
        return JSONResponse(
            status_code=500,
            content={"error": {"message": f"All accounts failed after {max_retries} attempts", "type": "server_error", "code": 500}}
        )
    
    # 不应该到达这里
    return JSONResponse(
        status_code=500,
        content={"error": {"message": "Unexpected error in request handling", "type": "server_error", "code": 500}}
    )


async def handle_chat_completion(request: ChatCompletionRequest):
    """Chat completion handler with per-request tool trace logging."""
    if not account_manager:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "Service not initialized", "type": "service_error", "code": 503}}
        )

    messages_list = []
    for msg in request.messages:
        msg_dict = {"role": msg.role, "content": msg.content}
        if msg.role == "tool" and msg.tool_call_id:
            msg_dict["tool_call_id"] = msg.tool_call_id
        if msg.role == "assistant" and msg.tool_calls:
            msg_dict["tool_calls"] = [tc.model_dump() if hasattr(tc, "model_dump") else tc for tc in msg.tool_calls]
        messages_list.append(msg_dict)

    disable_warp_tools = settings.get("disable_warp_tools", True)
    tools = None
    if request.tools:
        tools = [tool.model_dump() if hasattr(tool, "model_dump") else tool for tool in request.tools]

    effective_model = resolve_request_model(request.model, request.reasoning_effort)
    if effective_model != request.model:
        logger.info(
            "Resolved requested model '%s' with reasoning_effort='%s' to Warp model '%s'",
            request.model,
            request.reasoning_effort,
            effective_model,
        )

    trace_id = None
    if should_trace_request(messages_list, tools):
        trace_id = f"tool-{uuid.uuid4().hex[:12]}"
        log_tool_trace(
            "proxy_request_in",
            trace_id,
            request=summarize_openai_request(
                model=request.model,
                stream=request.stream,
                messages=messages_list,
                tools=tools,
                tool_choice=request.tool_choice,
                disable_warp_tools=disable_warp_tools,
                reasoning_effort=request.reasoning_effort,
                effective_model=effective_model,
            ),
        )

    max_retries = 3
    last_error = None

    for attempt in range(max_retries):
        account = None
        try:
            account = await account_manager.get_next_account()
            logger.info(
                f"[Attempt {attempt + 1}/{max_retries}] Using Warp account: {account.name} "
                f"for model: {request.model} (effective: {effective_model})"
            )

            client = account.get_warp_client()
            warp_stream = client.chat_completion(
                messages=messages_list,
                model=effective_model,
                stream=request.stream,
                disable_warp_tools=disable_warp_tools,
                tools=tools,
                trace_id=trace_id,
            )

            if request.stream:
                return StreamingResponse(
                    OpenAIAdapter.warp_to_openai_stream(warp_stream, request.model, trace_id=trace_id),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    }
                )

            response = await OpenAIAdapter.warp_to_openai_response(
                warp_stream,
                request.model,
                trace_id=trace_id,
            )
            return response

        except NoAvailableAccountError as e:
            if trace_id:
                log_tool_trace(
                    "proxy_error",
                    trace_id,
                    attempt=attempt + 1,
                    stage="account_selection",
                    error_type=type(e).__name__,
                    error=str(e),
                    will_retry=False,
                )
            logger.error(f"No available accounts: {e}")
            return JSONResponse(
                status_code=503,
                content={"error": {"message": "No available accounts", "type": "service_unavailable", "code": 503}}
            )

        except HTTPException as e:
            if trace_id:
                log_tool_trace(
                    "proxy_error",
                    trace_id,
                    attempt=attempt + 1,
                    account=account.name if account else None,
                    stage="handle_chat_completion",
                    error_type=type(e).__name__,
                    error=str(e),
                    http_status=e.status_code,
                    will_retry=e.status_code in (403, 429) and attempt < max_retries - 1,
                )
            if e.status_code == 403:
                logger.warning(f"Account returned 403, marking as blocked and retrying...")
                account.mark_blocked(403, "Blocked")
                last_error = e
                if attempt < max_retries - 1:
                    continue
                raise
            if e.status_code == 429:
                logger.warning(f"Account returned 429, marking as rate limited and retrying...")
                account.mark_blocked(429, "Too Many Requests")
                last_error = e
                if attempt < max_retries - 1:
                    continue
                raise
            raise

        except Exception as e:
            if trace_id:
                log_tool_trace(
                    "proxy_error",
                    trace_id,
                    attempt=attempt + 1,
                    account=account.name if account else None,
                    stage="handle_chat_completion",
                    error_type=type(e).__name__,
                    error=str(e),
                    will_retry=attempt < max_retries - 1,
                )
            error_str = str(e).lower()
            if "403" in error_str or "forbidden" in error_str or "unauthorized" in error_str:
                logger.warning(f"Account error (403-like): {e}, marking as blocked and retrying...")
                account.mark_blocked(403, "Blocked")
                last_error = e
                if attempt < max_retries - 1:
                    continue
                logger.error(f"All {max_retries} attempts failed")
                return JSONResponse(
                    status_code=500,
                    content={"error": {"message": f"All accounts failed: {str(e)}", "type": "server_error", "code": 500}}
                )
            if "429" in error_str or "too many" in error_str or "rate limit" in error_str:
                logger.warning(f"Account error (429-like): {e}, marking as rate limited and retrying...")
                account.mark_blocked(429, "Too Many Requests")
                last_error = e
                if attempt < max_retries - 1:
                    continue
                logger.error(f"All {max_retries} attempts failed")
                return JSONResponse(
                    status_code=500,
                    content={"error": {"message": f"All accounts failed: {str(e)}", "type": "server_error", "code": 500}}
                )
            if "failed to prepare" in error_str:
                logger.warning(f"Account prepare failed: {e}, retrying with next account...")
                last_error = e
                if attempt < max_retries - 1:
                    continue
                logger.error(f"All {max_retries} attempts failed")
                return JSONResponse(
                    status_code=500,
                    content={"error": {"message": f"All accounts failed: {str(e)}", "type": "server_error", "code": 500}}
                )
            return JSONResponse(
                status_code=500,
                content={"error": {"message": str(e), "type": "er_error", "code": 500}}
            )

    if last_error:
        logger.error(f"All {max_retries} attempts failed")
        return JSONResponse(
            status_code=500,
            content={"error": {"message": f"All accounts failed after {max_retries} attempts", "type": "server_error", "code": 500}}
        )

    return JSONResponse(
        status_code=500,
        content={"error": {"message": "Unexpected error in request handling", "type": "server_error", "code": 500}}
    )


# ==================== API 路由（多渠道支持）====================

# 默认路由
@app.post("/v1/chat/completions")
async def chat_completions_default(request: ChatCompletionRequest):
    """聊天完成接口"""
    return await handle_chat_completion(request)


# Warp 渠道明确路由
@app.post("/warp/v1/chat/completions")
async def chat_completions_warp(request: ChatCompletionRequest):
    """Warp 渠道聊天完成接口"""
    return await handle_chat_completion(request)


# ==================== Anthropic API 路由 ====================

async def handle_anthropic_completion(request: AnthropicMessagesRequest):
    """Anthropic Messages API 处理函数"""
    if not account_manager:
        return JSONResponse(
            status_code=503,
            content={"type": "error", "error": {"type": "api_error", "message": "Service not initialized"}}
        )
    
    max_retries = 3
    last_error = None
    
    for attempt in range(max_retries):
        account = None
        try:
            account = await account_manager.get_next_account()
            logger.info(f"[Anthropic][Attempt {attempt + 1}/{max_retries}] Using account: {account.name} for model: {request.model}")
            
            client = account.get_warp_client()
            
            # 将 Anthropic 消息转换为 Warp 格式
            messages_dict = [msg.model_dump() if hasattr(msg, 'model_dump') else msg for msg in request.messages]
            warp_messages = AnthropicAdapter.anthropic_to_warp_messages(request.system, messages_dict)
            
            disable_warp_tools = settings.get("disable_warp_tools", True)
            
            # 转换 tools
            tools = None
            if request.tools:
                tools = []
                for tool in request.tools:
                    tool_dict = tool.model_dump() if hasattr(tool, 'model_dump') else tool
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": tool_dict.get("name"),
                            "description": tool_dict.get("description"),
                            "parameters": tool_dict.get("input_schema", {"type": "object", "properties": {}})
                        }
                    })
            
            warp_stream = client.chat_completion(
                messages=warp_messages,
                model=request.model,
                stream=request.stream,
                disable_warp_tools=disable_warp_tools,
                tools=tools
            )
            
            if request.stream:
                return StreamingResponse(
                    AnthropicAdapter.warp_to_anthropic_stream(warp_stream, request.model),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    }
                )
            else:
                response = await AnthropicAdapter.warp_to_anthropic_response(warp_stream, request.model)
                return response
        
        except NoAvailableAccountError as e:
            logger.error(f"No available accounts: {e}")
            return JSONResponse(
                status_code=503,
                content={"type": "error", "error": {"type": "api_error", "message": "No available accounts"}}
            )
        
        except HTTPException as e:
            if e.status_code == 403:
                logger.warning(f"Account returned 403, marking as blocked and retrying...")
                account.mark_blocked(403, "Blocked")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue
                else:
                    raise
            elif e.status_code == 429:
                logger.warning(f"Account returned 429, marking as rate limited and retrying...")
                account.mark_blocked(429, "Too Many Requests")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue
                else:
                    raise
            else:
                raise
        
        except Exception as e:
            error_str = str(e).lower()
            if "403" in error_str or "forbidden" in error_str or "unauthorized" in error_str:
                logger.warning(f"Account error (403-like): {e}, marking as blocked and retrying...")
                account.mark_blocked(403, "Blocked")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    return JSONResponse(
                        status_code=500,
                        content={"type": "error", "error": {"type": "api_error", "message": f"All accounts failed: {str(e)}"}}
                    )
            elif "429" in error_str or "too many" in error_str or "rate limit" in error_str:
                logger.warning(f"Account error (429-like): {e}, marking as rate limited and retrying...")
                account.mark_blocked(429, "Too Many Requests")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    return JSONResponse(
                        status_code=500,
                        content={"type": "error", "error": {"type": "api_error", "message": f"All accounts failed: {str(e)}"}}
                    )
            elif "failed to prepare" in error_str:
                logger.warning(f"Account prepare failed: {e}, retrying with next account...")
                
                last_error = e
                if attempt < max_retries - 1:
                    continue
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    return JSONResponse(
                        status_code=500,
                        content={"type": "error", "error": {"type": "api_error", "message": f"All accounts failed: {str(e)}"}}
                    )
            else:
                return JSONResponse(
                    status_code=500,
                    content={"type": "error", "error": {"type": "api_error", "message": str(e)}}
                )
    
    if last_error:
        logger.error(f"All {max_retries} attempts failed")
        return JSONResponse(
            status_code=500,
            content={"type": "error", "error": {"type": "api_error", "message": f"All accounts failed after {max_retries} attempts"}}
        )
    
    return JSONResponse(
        status_code=500,
        content={"type": "error", "error": {"type": "api_error", "message": "Unexpected error in request handling"}}
    )


@app.post("/v1/messages")
async def anthropic_messages(request: AnthropicMessagesRequest):
    """Anthropic Messages API 兼容端点"""
    return await handle_anthropic_completion(request)


@app.post("/anthropic/v1/messages")
async def anthropic_messages_explicit(request: AnthropicMessagesRequest):
    """Anthropic 渠道明确路由"""
    return await handle_anthropic_completion(request)


@app.get("/test-stream")
async def test_stream():
    """测试流式输出是否正常"""
    import asyncio
    
    async def generate():
        for i in range(10):
            yield f"data: {{\"count\": {i}}}\n\n"
            await asyncio.sleep(0.5)  # 每0.5秒发送一次
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/stats")
async def get_stats():
    """获取统计信息"""
    if not account_manager:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    return account_manager.get_stats()


@app.get("/accounts/{account_name}/usage")
async def get_account_usage(account_name: str):
    """获取指定账号的用量信息"""
    if not account_manager:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    account = account_manager.get_account_by_name(account_name)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account '{account_name}' not found")
    
    try:
        client = WarpClient(account)
        usage = await client.get_usage()
        return usage
    except Exception as e:
        logger.error(f"Error getting usage for {account_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/accounts/reload")
async def reload_accounts():
    """重新加载账号配置文件"""
    global account_manager, settings
    
    config_dir = Path(__file__).parent / "config"
    accounts_dir = config_dir / "accounts" / "warp"
    settings_path = config_dir / "settings.json"
    
    try:
        # 重新加载设置
        if settings_path.exists():
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            logger.info(f"Reloaded settings from: {settings_path}")
        
        # 获取策略配置
        strategy_str = settings.get("account_strategy", "round-robin")
        try:
            strategy = StrategyType(strategy_str)
        except ValueError:
            logger.warning(f"Unknown strategy '{strategy_str}', using round-robin")
            strategy = StrategyType.ROUND_ROBIN
        
        auto_save = settings.get("auto_save_tokens", True)
        retry_429_interval = settings.get("retry_429_interval", 60)
        
        # 从目录重新加载账户
        account_manager = load_accounts_from_directory(
            accounts_dir=str(accounts_dir),
            strategy=strategy,
            auto_save=auto_save,
            retry_429_interval=retry_429_interval
        )
        
        logger.info(f"Reloaded {len(account_manager.accounts)} accounts")
        
        return {
            "status": "success",
            "message": f"Reloaded {len(account_manager.accounts)} accounts",
            "total_accounts": len(account_manager.accounts),
            "available_accounts": len(account_manager.get_available_accounts())
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reloading accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AddAccountRequest(BaseModel):
    """新增账户请求"""
    name: Optional[str] = None
    refresh_token: str


@app.post("/accounts/add")
async def add_account(request: AddAccountRequest):
    """新增账户"""
    global account_manager
    
    if not account_manager:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    config_dir = Path(__file__).parent / "config"
    accounts_dir = config_dir / "accounts" / "warp"
    
    try:
        # 生成账户名
        name = request.name or f"account_{len(account_manager.accounts) + 1}"
        
        # 检查名称是否重复
        if account_manager.get_account_by_name(name):
            raise HTTPException(status_code=400, detail=f"Account '{name}' already exists")
        
        # 创建新账户对象
        new_account = Account(
            name=name,
            refresh_token=request.refresh_token,
            enabled=True
        )
        new_account.account_manager = account_manager
        
        # 添加到内存
        account_manager.accounts.append(new_account)
        
        # 保存到单独的文件
        await account_manager.save_account(new_account)
        
        logger.info(f"Added new account: {name}")
        
        return {
            "status": "success",
            "name": name,
            "message": f"Account '{name}' added successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/accounts/refresh")
async def refresh_all_accounts():
    """刷新所有账号的token"""
    if not account_manager:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        await account_manager.refresh_all_tokens()
        return {"status": "success", "message": "All tokens refreshed"}
    except Exception as e:
        logger.error(f"Error refreshing tokens: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/accounts/delete-blocked")
async def delete_blocked_accounts():
    """删除所有 403 封禁的账户"""
    global account_manager
    
    if not account_manager:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        # 找出所有 403 封禁的账户
        blocked_accounts = [acc for acc in account_manager.accounts if acc.status_code == "403"]
        
        if not blocked_accounts:
            return {
                "status": "success",
                "message": "No blocked accounts found",
                "deleted_count": 0
            }
        
        deleted_count = 0
        deleted_names = []
        
        for account in blocked_accounts:
            # 从内存中移除
            account_manager.accounts.remove(account)
            # 删除文件
            await account_manager.delete_account_file(account.name)
            deleted_count += 1
            deleted_names.append(account.name)
        
        logger.info(f"Deleted {deleted_count} blocked accounts: {deleted_names}")
        
        return {
            "status": "success",
            "message": f"Deleted {deleted_count} blocked accounts",
            "deleted_count": deleted_count,
            "deleted_accounts": deleted_names
        }
    except Exception as e:
        logger.error(f"Error deleting blocked accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 后台任务 ====================

async def test_accounts_and_fetch_info():
    """测试账号登录并获取模型和用量信息（只测试第一个启用的账号）"""
    if not account_manager:
        return
    
    logger.info("=" * 60)
    logger.info("Testing First Account and Fetching Information")
    logger.info("=" * 60)
    
    # 只测试第一个启用的账号
    first_account = None
    for account in account_manager.accounts:
        if account.enabled:
            first_account = account
            break
    
    if not first_account:
        logger.warning("No enabled accounts found")
        return
    
    try:
        logger.info(f"Testing account: {first_account.name}")
        
        # 创建客户端
        from core.warp_client import WarpClient
        client = WarpClient(first_account)
        
        # 执行登录
        logger.info(f"  Logging in...")
        login_success = await client.login()
        
        if login_success:
            logger.info(f"  ✅ Login successful")
            
            # 测试发送消息（如果配置中启用了）
            if settings.get("test_message_on_startup", False):
                test_model = settings.get("test_model", "claude-4-5-opus")
                test_query = settings.get("test_query", "你好")
                
                logger.info(f"  🧪 Testing message with model: {test_model}")
                logger.info(f"  📝 Query: {test_query}")
                
                try:
                    # 构建消息列表
                    messages = [{"role": "user", "content": test_query}]
                    
                    event_count = 0
                    async for event in client.chat_completion(
                        messages,
                        test_model,
                        disable_warp_tools=settings.get("disable_warp_tools", True),
                    ):
                        event_count += 1
                        if event_count <= 3:  # 只显示前3个事件
                            logger.info(f"     Event #{event_count}: {list(event.keys())}")
                    
                    logger.info(f"  ✅ Message test completed: {event_count} events received")
                except Exception as e:
                    logger.error(f"  ❌ Message test failed: {e}")
            else:
                logger.info(f"  ℹ️  Message test disabled (set 'test_message_on_startup': true to enable)")
            
            # 获取用量信息
            logger.info(f"  Fetching usage info...")
            usage = await client.get_usage()
            
            if usage:
                is_unlimited = usage.get("isUnlimited", False)
                request_limit = usage.get("requestLimit", 0)
                requests_used = usage.get("requestsUsedSinceLastRefresh", 0)
                next_refresh = usage.get("nextRefreshTime", "N/A")
                refresh_duration = usage.get("requestLimitRefreshDuration", "N/A")
                
                logger.info(f"  📊 Usage Information:")
                if is_unlimited:
                    logger.info(f"     ✨ Unlimited requests")
                else:
                    remaining = request_limit - requests_used
                    usage_percent = (requests_used / request_limit * 100) if request_limit > 0 else 0
                    logger.info(f"     Request Limit: {request_limit}")
                    logger.info(f"     Requests Used: {requests_used} ({usage_percent:.1f}%)")
                    logger.info(f"     Remaining: {remaining}")
                logger.info(f"     Refresh Period: {refresh_duration}")
                logger.info(f"     Next Refresh: {next_refresh}")
            else:
                logger.warning(f"  ⚠️ Failed to fetch usage info")
            
            # 获取模型信息（使用GraphQL）
            logger.info(f"  Fetching available models...")
            try:
                # 确保有有效的JWT
                if first_account.is_jwt_expired():
                    await client.refresh_token()
                
                # 调用GraphQL获取模型
                models_data = await get_feature_model_choices_custom(client)
                
                if models_data:
                    # 提取模型信息
                    user_data = models_data.get("data", {}).get("user", {})
                    if user_data.get("__typename") == "UserOutput":
                        workspaces = user_data.get("user", {}).get("workspaces", [])
                        if workspaces:
                            feature_model_choice = workspaces[0].get("featureModelChoice", {})
                            
                            # 显示agentMode模型列表
                            agent_mode = feature_model_choice.get("agentMode", {})
                            choices = agent_mode.get("choices", [])
                            default_id = agent_mode.get("defaultId", "N/A")
                            
                            logger.info(f"  📋 Available Agent Mode Models (Total: {len(choices)}):")
                            logger.info(f"     Default: {default_id}")
                            logger.info("")
                            
                            # 显示所有模型
                            if choices:
                                for model in choices:
                                    display_name = model.get("displayName", "N/A")
                                    model_id = model.get("id", "N/A")
                                    provider = model.get("provider", "N/A")
                                    reasoning = model.get("reasoningLevel", "Off")
                                    vision = "👁️" if model.get("visionSupported", False) else ""
                                    disabled = model.get("disableReason")
                                    
                                    status = "❌ DISABLED" if disabled else "✅"
                                    logger.info(f"     {status} {display_name} ({model_id})")
                                    logger.info(f"        Provider: {provider} | Reasoning: {reasoning} {vision}")
                                    if disabled:
                                        logger.info(f"        Reason: {disabled}")
                else:
                    logger.warning(f"  ⚠️ Failed to fetch model info")
                    
            except Exception as e:
                logger.warning(f"  ⚠️ Error fetching models: {e}")
            
        else:
            logger.error(f"  ❌ Login failed")
            
    except Exception as e:
        logger.error(f"  ❌ Error testing account {first_account.name}: {e}")
    
    logger.info("=" * 60)
    logger.info("Account Testing Complete")
    logger.info("=" * 60)


async def get_feature_model_choices_custom(client):
    """获取模型选择（自定义实现）"""
    import httpx
    
    query = """query GetFeatureModelChoices($requestContext: RequestContext!) {
  user(requestContext: $requestContext) {
    __typename
    ... on UserOutput {
      user {
        workspaces {
          featureModelChoice {
            agentMode {
              defaultId
              choices {
                displayName
                baseModelName
                id
                reasoningLevel
                usageMetadata {
                  creditMultiplier
                  requestMultiplier
                }
                description
                disableReason
                visionSupported
                spec {
                  cost
                  quality
                  speed
                }
                provider
              }
            }
          }
        }
      }
    }
  }
}
"""
    
    # 使用本地导入的CLIENT_VERSION等
    from warp2protobuf.config.settings import CLIENT_VERSION, OS_CATEGORY, OS_NAME, OS_VERSION, get_warp_client_headers, get_httpx_client_kwargs
    
    variables = {
        "requestContext": {
            "clientContext": {"version": CLIENT_VERSION},
            "osContext": {
                "category": OS_CATEGORY,
                "linuxKernelVersion": None,
                "name": OS_NAME,
                "version": OS_VERSION
            }
        }
    }
    
    headers = {
        **get_warp_client_headers(),
        "content-type": "application/json",
        "authorization": f"Bearer {client.account.jwt_token}",
        "accept": "*/*",
        "accept-encoding": "gzip,br",
    }
    
    try:
        async with httpx.AsyncClient(**get_httpx_client_kwargs(timeout=httpx.Timeout(30.0), verify=not client.insecure_tls)) as http_client:
            response = await http_client.post(
                "https://app.warp.dev/graphql/v2?op=GetFeatureModelChoices",
                json={"query": query, "variables": variables, "operationName": "GetFeatureModelChoices"},
                headers=headers
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"GraphQL query failed: HTTP {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"GraphQL query exception: {e}")
        return None


# ==================== 启动事件 ====================

@app.on_event("startup")
async def startup_event():
    """服务器启动时初始化"""
    global account_manager, settings, accounts_config
    
    logger.info("=" * 60)
    logger.info("Warp2OpenAI Simplified Server Starting")
    logger.info("=" * 60)
    
    config_dir = Path(__file__).parent / "config"
    settings_path = config_dir / "settings.json"
    accounts_path = config_dir / "accounts.json"
    
    # 加载设置文件
    if settings_path.exists():
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        logger.info(f"Loaded settings from: {settings_path}")
        
        # 应用日志级别设置
        log_level = settings.get("logging", {}).get("level", "INFO")
        _apply_log_level(log_level)
        logger.info(f"Log level set to: {log_level}")
    else:
        logger.warning(f"Settings file not found: {settings_path}, using defaults")
        settings = {}
    
    # 加载账号文件
    accounts_dir = config_dir / "accounts" / "warp"
    
    try:
        # 获取策略配置
        strategy_str = settings.get("account_strategy", "round-robin")
        try:
            strategy = StrategyType(strategy_str)
        except ValueError:
            logger.warning(f"Unknown strategy '{strategy_str}', using round-robin")
            strategy = StrategyType.ROUND_ROBIN
        
        auto_save = settings.get("auto_save_tokens", True)
        retry_429_interval = settings.get("retry_429_interval", 60)
        
        # 从目录加载账户
        account_manager = load_accounts_from_directory(
            accounts_dir=str(accounts_dir),
            strategy=strategy,
            auto_save=auto_save,
            retry_429_interval=retry_429_interval
        )
        
        logger.info(f"Initialized with {len(account_manager.accounts)} accounts")
        logger.info(f"Strategy: {account_manager.strategy.value}")
        logger.info(f"Auto-save tokens: {account_manager.auto_save}")
        logger.info(f"Retry 429 interval: {retry_429_interval} minutes")
        
        # Token 刷新策略：按需刷新（在每次请求前通过 ensure_ready() 检查）
        logger.info("Token refresh will be done on-demand when accounts are used")
        
        # 测试登录并获取信息
        logger.info("Testing account login and fetching info...")
        await test_accounts_and_fetch_info()
        
        # 显示账号状态
        stats = account_manager.get_stats()
        logger.info(f"Available accounts: {stats['available_accounts']}/{stats['total_accounts']}")
        
        for acc_info in stats['accounts']:
            if acc_info['enabled']:
                status = "✅" if acc_info['status_code'] != 'quota_exceeded' else "❌"
                logger.info(f"  {status} {acc_info['name']}: {acc_info['quota_remaining']}/{acc_info['quota_limit']} remaining")
        
        logger.info("=" * 60)
        logger.info("Server ready!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Failed to initialize: {e}", exc_info=True)
        sys.exit(1)


# ==================== 主函数 ====================

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Warp2OpenAI Simplified Server")
    parser.add_argument("--host", default=None, help="Host to bind to (overrides settings.json)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to (overrides settings.json)")
    parser.add_argument("--log-level", default=None, choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Log level (overrides settings.json)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes (development mode)")
    
    args = parser.parse_args()
    
    # 加载settings.json获取默认值
    settings_path = Path(__file__).parent / "config" / "settings.json"
    server_settings = {}
    log_level = "INFO"
    
    if settings_path.exists():
        with open(settings_path, 'r', encoding='utf-8') as f:
            file_settings = json.load(f)
            server_settings = file_settings.get("server", {})
            log_level = file_settings.get("logging", {}).get("level", "INFO")
    
    # 命令行参数优先级更高
    host = args.host or server_settings.get("host", "0.0.0.0")
    port = args.port or server_settings.get("port", 9980)
    log_level = args.log_level or log_level
    
    # 设置日志级别
    _apply_log_level(log_level)
    
    # 启动服务器
    uvicorn.run(
        "server:app",  # 使用字符串形式以支持 reload
        host=host,
        port=port,
        log_level=log_level.lower(),
        reload=args.reload  # 启用热重载
    )


if __name__ == "__main__":
    main()
