#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration settings for Warp API server

Contains environment variables, paths, and constants.
"""
import os
import pathlib
import importlib.util
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Path configurations - 修改为相对于python目录
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
PROTO_DIR = SCRIPT_DIR / "proto"
LOGS_DIR = SCRIPT_DIR / "logs"

# API configuration
WARP_URL = "https://app.warp.dev/ai/multi-agent"

# Environment variables with defaults
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8002"))
WARP_JWT = os.getenv("WARP_JWT")

# Client headers configuration
CLIENT_ID = os.getenv("WARP_CLIENT_ID", "warp-app")
CLIENT_VERSION = os.getenv("WARP_CLIENT_VERSION", "v0.2026.03.18.08.24.stable_01")
OS_CATEGORY = os.getenv("WARP_OS_CATEGORY", "Windows")
OS_NAME = os.getenv("WARP_OS_NAME", "Windows")
OS_VERSION = os.getenv("WARP_OS_VERSION", "11 (26100)")


def get_warp_client_headers(include_client_id: bool = True) -> dict[str, str]:
    headers = {
        "x-warp-client-version": CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": OS_VERSION,
    }
    if include_client_id:
        headers["x-warp-client-id"] = CLIENT_ID
    return headers


def has_http2_support() -> bool:
    return importlib.util.find_spec("h2") is not None


def get_httpx_client_kwargs(*, timeout, verify=True, trust_env=False, http2: bool | None = None) -> dict:
    client_http2 = has_http2_support() if http2 is None else (http2 and has_http2_support())
    kwargs = {
        "timeout": timeout,
        "verify": verify,
        "http2": client_http2,
    }
    if trust_env:
        kwargs["trust_env"] = True
    return kwargs

# Protobuf field names for text detection
TEXT_FIELD_NAMES = ("text", "prompt", "query", "content", "message", "input")
PATH_HINT_BONUS = ("conversation", "query", "input", "user", "request", "delta")

# Response parsing configuration
SYSTEM_STR = {"agent_output.text", "server_message_data", "USER_INITIATED", "agent_output", "text"}

# JWT refresh configuration
REFRESH_TOKEN_B64 = "Z3JhbnRfdHlwZT1yZWZyZXNoX3Rva2VuJnJlZnJlc2hfdG9rZW49QU1mLXZCeFNSbWRodmVHR0JZTTY5cDA1a0RoSW4xaTd3c2NBTEVtQzlmWURScEh6akVSOWRMN2trLWtIUFl3dlk5Uk9rbXk1MHFHVGNJaUpaNEFtODZoUFhrcFZQTDkwSEptQWY1Zlo3UGVqeXBkYmNLNHdzbzhLZjNheGlTV3RJUk9oT2NuOU56R2FTdmw3V3FSTU5PcEhHZ0JyWW40SThrclc1N1I4X3dzOHU3WGNTdzh1MERpTDlIcnBNbTBMdHdzQ2g4MWtfNmJiMkNXT0ViMWxJeDNIV1NCVGVQRldzUQ=="
REFRESH_URL = "https://app.warp.dev/proxy/token?key=AIzaSyBdy3O3S9hrdayLJxJ7mriBR4qgUaUygAs" 
