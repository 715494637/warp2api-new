#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Model configuration and catalog for Warp API.

The catalog below is a local snapshot of Warp's upstream model choices captured
from GraphQL on 2026-03-20. Request-time model mapping intentionally remains
permissive so newly-added upstream ids can still be passed through directly.
"""
import re
import time


MODEL_ALIASES = {
    "claude-4.5-haiku": "claude-4-5-haiku",
    "claude-4.5-opus": "claude-4-5-opus",
    "claude-4.5-opus-thinking": "claude-4-5-opus-thinking",
    "claude-4.5-sonnet": "claude-4-5-sonnet",
    "claude-4.5-sonnet-thinking": "claude-4-5-sonnet-thinking",
    "gpt-5-high-reasoning": "gpt-5 (high reasoning)",
}

PROVIDER_OWNERS = {
    "ANTHROPIC": "anthropic",
    "GOOGLE": "google",
    "OPENAI": "openai",
    "UNKNOWN": "warp",
}

MODEL_METADATA = {
    "auto": {
        "display_name": "auto (responsive)",
        "provider": "UNKNOWN",
        "vision_supported": True,
        "reasoning_level": None,
        "description": None,
    },
    "auto-efficient": {
        "display_name": "auto (cost-efficient)",
        "provider": "UNKNOWN",
        "vision_supported": True,
        "reasoning_level": None,
        "description": None,
    },
    "auto-genius": {
        "display_name": "auto (genius)",
        "provider": "UNKNOWN",
        "vision_supported": True,
        "reasoning_level": None,
        "description": None,
    },
    "claude-4-sonnet": {
        "display_name": "claude 4 sonnet",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": "Off",
        "description": None,
    },
    "claude-4.1-opus": {
        "display_name": "claude 4.1 opus",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": None,
        "description": None,
    },
    "claude-4-5-haiku": {
        "display_name": "claude 4.5 haiku",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": None,
        "description": None,
    },
    "claude-4-5-opus": {
        "display_name": "claude 4.5 opus",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": "Off",
        "description": None,
    },
    "claude-4-5-opus-thinking": {
        "display_name": "claude 4.5 opus (thinking)",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": "Thinking",
        "description": None,
    },
    "claude-4-5-sonnet": {
        "display_name": "claude 4.5 sonnet",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": "Off",
        "description": None,
    },
    "claude-4-5-sonnet-thinking": {
        "display_name": "claude 4.5 sonnet (thinking)",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": "Thinking",
        "description": None,
    },
    "claude-4-6-opus-high": {
        "display_name": "claude 4.6 opus",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": "Default",
        "description": None,
    },
    "claude-4-6-opus-max": {
        "display_name": "claude 4.6 opus (max)",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": "Max",
        "description": None,
    },
    "claude-4-6-sonnet-high": {
        "display_name": "claude 4.6 sonnet",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": "Default",
        "description": None,
    },
    "claude-4-6-sonnet-max": {
        "display_name": "claude 4.6 sonnet (max)",
        "provider": "ANTHROPIC",
        "vision_supported": True,
        "reasoning_level": "Max",
        "description": None,
    },
    "gemini-2.5-pro": {
        "display_name": "gemini 2.5 pro",
        "provider": "GOOGLE",
        "vision_supported": True,
        "reasoning_level": None,
        "description": None,
    },
    "gemini-3-pro": {
        "display_name": "gemini 3 pro",
        "provider": "GOOGLE",
        "vision_supported": True,
        "reasoning_level": None,
        "description": None,
    },
    "gemini-3.1-pro": {
        "display_name": "gemini 3.1 pro",
        "provider": "GOOGLE",
        "vision_supported": True,
        "reasoning_level": None,
        "description": None,
    },
    "glm-47-fireworks": {
        "display_name": "glm 4.7",
        "provider": "UNKNOWN",
        "vision_supported": False,
        "reasoning_level": None,
        "description": "us-hosted",
    },
    "glm-5-fireworks": {
        "display_name": "glm 5",
        "provider": "UNKNOWN",
        "vision_supported": False,
        "reasoning_level": None,
        "description": "us-hosted",
    },
    "gpt-5-low-reasoning": {
        "display_name": "gpt-5 (low reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Low",
        "description": None,
    },
    "gpt-5": {
        "display_name": "gpt-5 (medium reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Medium",
        "description": None,
    },
    "gpt-5 (high reasoning)": {
        "display_name": "gpt-5 (high reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "High",
        "description": None,
    },
    "gpt-5-1-low-reasoning": {
        "display_name": "gpt-5.1 (low reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Low",
        "description": None,
    },
    "gpt-5-1-medium-reasoning": {
        "display_name": "gpt-5.1 (medium reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Medium",
        "description": None,
    },
    "gpt-5-1-high-reasoning": {
        "display_name": "gpt-5.1 (high reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "High",
        "description": None,
    },
    "gpt-5-1-codex-low": {
        "display_name": "gpt-5.1 codex (low reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Low",
        "description": None,
    },
    "gpt-5-1-codex-medium": {
        "display_name": "gpt-5.1 codex (medium reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Medium",
        "description": None,
    },
    "gpt-5-1-codex-high": {
        "display_name": "gpt-5.1 codex (high reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "High",
        "description": None,
    },
    "gpt-5-1-codex-max-low": {
        "display_name": "gpt-5.1 codex max (low reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Low",
        "description": None,
    },
    "gpt-5-1-codex-max-medium": {
        "display_name": "gpt-5.1 codex max (medium reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Medium",
        "description": None,
    },
    "gpt-5-1-codex-max-high": {
        "display_name": "gpt-5.1 codex max (high reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "High",
        "description": None,
    },
    "gpt-5-1-codex-max-xhigh": {
        "display_name": "gpt-5.1 codex max (xhigh reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Xhigh",
        "description": None,
    },
    "gpt-5-2-low": {
        "display_name": "gpt-5.2 (low reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Low",
        "description": None,
    },
    "gpt-5-2-medium": {
        "display_name": "gpt-5.2 (medium reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Medium",
        "description": None,
    },
    "gpt-5-2-high": {
        "display_name": "gpt-5.2 (high reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "High",
        "description": None,
    },
    "gpt-5-2-xhigh": {
        "display_name": "gpt-5.2 (xhigh reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Xhigh",
        "description": None,
    },
    "gpt-5-2-codex-low": {
        "display_name": "gpt-5.2 codex (low reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Low",
        "description": None,
    },
    "gpt-5-2-codex-medium": {
        "display_name": "gpt-5.2 codex (medium reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Medium",
        "description": None,
    },
    "gpt-5-2-codex-high": {
        "display_name": "gpt-5.2 codex (high reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "High",
        "description": None,
    },
    "gpt-5-2-codex-xhigh": {
        "display_name": "gpt-5.2 codex (xhigh reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Xhigh",
        "description": None,
    },
    "gpt-5-3-codex-low": {
        "display_name": "gpt-5.3 codex (low reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Low",
        "description": None,
    },
    "gpt-5-3-codex-medium": {
        "display_name": "gpt-5.3 codex (medium reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Medium",
        "description": None,
    },
    "gpt-5-3-codex-high": {
        "display_name": "gpt-5.3 codex (high reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "High",
        "description": None,
    },
    "gpt-5-3-codex-xhigh": {
        "display_name": "gpt-5.3 codex (xhigh reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Xhigh",
        "description": None,
    },
    "gpt-5-4-low": {
        "display_name": "gpt-5.4 (low reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Low",
        "description": None,
    },
    "gpt-5-4-medium": {
        "display_name": "gpt-5.4 (medium reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Medium",
        "description": None,
    },
    "gpt-5-4-high": {
        "display_name": "gpt-5.4 (high reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "High",
        "description": None,
    },
    "gpt-5-4-xhigh": {
        "display_name": "gpt-5.4 (xhigh reasoning)",
        "provider": "OPENAI",
        "vision_supported": True,
        "reasoning_level": "Xhigh",
        "description": None,
    },
    "kimi-k25-fireworks": {
        "display_name": "kimi k2.5",
        "provider": "UNKNOWN",
        "vision_supported": True,
        "reasoning_level": None,
        "description": "us-hosted",
    },
    "cli-agent-auto": {
        "display_name": "auto",
        "provider": "UNKNOWN",
        "vision_supported": False,
        "reasoning_level": None,
        "description": None,
    },
}

CATEGORY_MODELS = {
    "agent_mode": {
        "default": "auto-genius",
        "model_ids": [
            "auto",
            "auto-efficient",
            "auto-genius",
            "claude-4-sonnet",
            "claude-4.1-opus",
            "claude-4-5-haiku",
            "claude-4-5-opus",
            "claude-4-5-opus-thinking",
            "claude-4-5-sonnet",
            "claude-4-5-sonnet-thinking",
            "claude-4-6-opus-high",
            "claude-4-6-opus-max",
            "claude-4-6-sonnet-high",
            "claude-4-6-sonnet-max",
            "gemini-2.5-pro",
            "gemini-3-pro",
            "gemini-3.1-pro",
            "glm-47-fireworks",
            "glm-5-fireworks",
            "gpt-5-low-reasoning",
            "gpt-5",
            "gpt-5 (high reasoning)",
            "gpt-5-1-low-reasoning",
            "gpt-5-1-medium-reasoning",
            "gpt-5-1-high-reasoning",
            "gpt-5-1-codex-low",
            "gpt-5-1-codex-medium",
            "gpt-5-1-codex-high",
            "gpt-5-1-codex-max-low",
            "gpt-5-1-codex-max-medium",
            "gpt-5-1-codex-max-high",
            "gpt-5-1-codex-max-xhigh",
            "gpt-5-2-low",
            "gpt-5-2-medium",
            "gpt-5-2-high",
            "gpt-5-2-xhigh",
            "gpt-5-2-codex-low",
            "gpt-5-2-codex-medium",
            "gpt-5-2-codex-high",
            "gpt-5-2-codex-xhigh",
            "gpt-5-3-codex-low",
            "gpt-5-3-codex-medium",
            "gpt-5-3-codex-high",
            "gpt-5-3-codex-xhigh",
            "gpt-5-4-low",
            "gpt-5-4-medium",
            "gpt-5-4-high",
            "gpt-5-4-xhigh",
            "kimi-k25-fireworks",
        ],
    },
    "planning": {
        "default": "gpt-5 (high reasoning)",
        "model_ids": [
            "claude-4.1-opus",
            "claude-4-5-sonnet",
            "claude-4-5-sonnet-thinking",
            "claude-4-6-sonnet-high",
            "claude-4-6-sonnet-max",
            "gemini-2.5-pro",
            "gpt-5 (high reasoning)",
            "gpt-5-1-high-reasoning",
        ],
    },
    "coding": {
        "default": "auto-genius",
        "model_ids": [
            "auto",
            "auto-efficient",
            "auto-genius",
            "claude-4-sonnet",
            "claude-4.1-opus",
            "claude-4-5-haiku",
            "claude-4-5-opus",
            "claude-4-5-opus-thinking",
            "claude-4-5-sonnet",
            "claude-4-5-sonnet-thinking",
            "claude-4-6-opus-high",
            "claude-4-6-opus-max",
            "claude-4-6-sonnet-high",
            "claude-4-6-sonnet-max",
            "gemini-2.5-pro",
            "gemini-3-pro",
            "gemini-3.1-pro",
            "glm-47-fireworks",
            "glm-5-fireworks",
            "gpt-5-low-reasoning",
            "gpt-5",
            "gpt-5 (high reasoning)",
            "gpt-5-1-low-reasoning",
            "gpt-5-1-medium-reasoning",
            "gpt-5-1-high-reasoning",
            "gpt-5-1-codex-low",
            "gpt-5-1-codex-medium",
            "gpt-5-1-codex-high",
            "gpt-5-1-codex-max-low",
            "gpt-5-1-codex-max-medium",
            "gpt-5-1-codex-max-high",
            "gpt-5-1-codex-max-xhigh",
            "gpt-5-2-low",
            "gpt-5-2-medium",
            "gpt-5-2-high",
            "gpt-5-2-xhigh",
            "gpt-5-2-codex-low",
            "gpt-5-2-codex-medium",
            "gpt-5-2-codex-high",
            "gpt-5-2-codex-xhigh",
            "gpt-5-3-codex-low",
            "gpt-5-3-codex-medium",
            "gpt-5-3-codex-high",
            "gpt-5-3-codex-xhigh",
            "gpt-5-4-low",
            "gpt-5-4-medium",
            "gpt-5-4-high",
            "gpt-5-4-xhigh",
            "kimi-k25-fireworks",
        ],
    },
    "cli_agent": {
        "default": "cli-agent-auto",
        "model_ids": [
            "cli-agent-auto",
            "claude-4-sonnet",
            "claude-4.1-opus",
            "claude-4-5-haiku",
            "claude-4-5-opus",
            "claude-4-5-opus-thinking",
            "claude-4-5-sonnet",
            "claude-4-5-sonnet-thinking",
            "claude-4-6-opus-high",
            "claude-4-6-opus-max",
            "claude-4-6-sonnet-high",
            "claude-4-6-sonnet-max",
            "gemini-2.5-pro",
            "gemini-3-pro",
            "gemini-3.1-pro",
            "glm-47-fireworks",
            "glm-5-fireworks",
            "gpt-5-low-reasoning",
            "gpt-5",
            "gpt-5 (high reasoning)",
            "gpt-5-1-low-reasoning",
            "gpt-5-1-medium-reasoning",
            "gpt-5-1-high-reasoning",
            "gpt-5-1-codex-low",
            "gpt-5-1-codex-medium",
            "gpt-5-1-codex-high",
            "gpt-5-1-codex-max-low",
            "gpt-5-1-codex-max-medium",
            "gpt-5-1-codex-max-high",
            "gpt-5-1-codex-max-xhigh",
            "gpt-5-2-low",
            "gpt-5-2-medium",
            "gpt-5-2-high",
            "gpt-5-2-xhigh",
            "gpt-5-2-codex-low",
            "gpt-5-2-codex-medium",
            "gpt-5-2-codex-high",
            "gpt-5-2-codex-xhigh",
            "gpt-5-3-codex-low",
            "gpt-5-3-codex-medium",
            "gpt-5-3-codex-high",
            "gpt-5-3-codex-xhigh",
            "gpt-5-4-low",
            "gpt-5-4-medium",
            "gpt-5-4-high",
            "gpt-5-4-xhigh",
            "kimi-k25-fireworks",
        ],
    },
}

RECOGNIZED_REASONING_EFFORTS = {
    "none",
    "auto",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
}

REASONING_MODEL_FAMILIES = {
    "claude-4-5-opus": {
        "default": "claude-4-5-opus-thinking",
        "aliases": {"claude-4-5-opus"},
        "levels": {
            "none": "claude-4-5-opus",
            "auto": "claude-4-5-opus-thinking",
            "minimal": "claude-4-5-opus-thinking",
            "low": "claude-4-5-opus-thinking",
            "medium": "claude-4-5-opus-thinking",
            "high": "claude-4-5-opus-thinking",
            "xhigh": "claude-4-5-opus-thinking",
            "max": "claude-4-5-opus-thinking",
        },
    },
    "claude-4-5-sonnet": {
        "default": "claude-4-5-sonnet-thinking",
        "aliases": {"claude-4-5-sonnet"},
        "levels": {
            "none": "claude-4-5-sonnet",
            "auto": "claude-4-5-sonnet-thinking",
            "minimal": "claude-4-5-sonnet-thinking",
            "low": "claude-4-5-sonnet-thinking",
            "medium": "claude-4-5-sonnet-thinking",
            "high": "claude-4-5-sonnet-thinking",
            "xhigh": "claude-4-5-sonnet-thinking",
            "max": "claude-4-5-sonnet-thinking",
        },
    },
    "claude-4-6-opus": {
        "default": "claude-4-6-opus-high",
        "aliases": {"claude-4-6-opus"},
        "levels": {
            "auto": "claude-4-6-opus-high",
            "minimal": "claude-4-6-opus-high",
            "low": "claude-4-6-opus-high",
            "medium": "claude-4-6-opus-high",
            "high": "claude-4-6-opus-high",
            "xhigh": "claude-4-6-opus-max",
            "max": "claude-4-6-opus-max",
        },
    },
    "claude-4-6-sonnet": {
        "default": "claude-4-6-sonnet-high",
        "aliases": {"claude-4-6-sonnet"},
        "levels": {
            "auto": "claude-4-6-sonnet-high",
            "minimal": "claude-4-6-sonnet-high",
            "low": "claude-4-6-sonnet-high",
            "medium": "claude-4-6-sonnet-high",
            "high": "claude-4-6-sonnet-high",
            "xhigh": "claude-4-6-sonnet-max",
            "max": "claude-4-6-sonnet-max",
        },
    },
    "gpt-5": {
        "default": "gpt-5",
        "aliases": {"gpt-5"},
        "levels": {
            "auto": "gpt-5",
            "minimal": "gpt-5-low-reasoning",
            "low": "gpt-5-low-reasoning",
            "medium": "gpt-5",
            "high": "gpt-5 (high reasoning)",
            "xhigh": "gpt-5 (high reasoning)",
            "max": "gpt-5 (high reasoning)",
        },
    },
    "gpt-5-1": {
        "default": "gpt-5-1-medium-reasoning",
        "aliases": {"gpt-5-1"},
        "levels": {
            "auto": "gpt-5-1-medium-reasoning",
            "minimal": "gpt-5-1-low-reasoning",
            "low": "gpt-5-1-low-reasoning",
            "medium": "gpt-5-1-medium-reasoning",
            "high": "gpt-5-1-high-reasoning",
            "xhigh": "gpt-5-1-high-reasoning",
            "max": "gpt-5-1-high-reasoning",
        },
    },
    "gpt-5-1-codex": {
        "default": "gpt-5-1-codex-medium",
        "aliases": {"gpt-5-1-codex"},
        "levels": {
            "auto": "gpt-5-1-codex-medium",
            "minimal": "gpt-5-1-codex-low",
            "low": "gpt-5-1-codex-low",
            "medium": "gpt-5-1-codex-medium",
            "high": "gpt-5-1-codex-high",
            "xhigh": "gpt-5-1-codex-high",
            "max": "gpt-5-1-codex-high",
        },
    },
    "gpt-5-1-codex-max": {
        "default": "gpt-5-1-codex-max-medium",
        "aliases": {"gpt-5-1-codex-max"},
        "levels": {
            "auto": "gpt-5-1-codex-max-medium",
            "minimal": "gpt-5-1-codex-max-low",
            "low": "gpt-5-1-codex-max-low",
            "medium": "gpt-5-1-codex-max-medium",
            "high": "gpt-5-1-codex-max-high",
            "xhigh": "gpt-5-1-codex-max-xhigh",
            "max": "gpt-5-1-codex-max-xhigh",
        },
    },
    "gpt-5-2": {
        "default": "gpt-5-2-medium",
        "aliases": {"gpt-5-2"},
        "levels": {
            "auto": "gpt-5-2-medium",
            "minimal": "gpt-5-2-low",
            "low": "gpt-5-2-low",
            "medium": "gpt-5-2-medium",
            "high": "gpt-5-2-high",
            "xhigh": "gpt-5-2-xhigh",
            "max": "gpt-5-2-xhigh",
        },
    },
    "gpt-5-2-codex": {
        "default": "gpt-5-2-codex-medium",
        "aliases": {"gpt-5-2-codex"},
        "levels": {
            "auto": "gpt-5-2-codex-medium",
            "minimal": "gpt-5-2-codex-low",
            "low": "gpt-5-2-codex-low",
            "medium": "gpt-5-2-codex-medium",
            "high": "gpt-5-2-codex-high",
            "xhigh": "gpt-5-2-codex-xhigh",
            "max": "gpt-5-2-codex-xhigh",
        },
    },
    "gpt-5-3-codex": {
        "default": "gpt-5-3-codex-medium",
        "aliases": {"gpt-5-3-codex"},
        "levels": {
            "auto": "gpt-5-3-codex-medium",
            "minimal": "gpt-5-3-codex-low",
            "low": "gpt-5-3-codex-low",
            "medium": "gpt-5-3-codex-medium",
            "high": "gpt-5-3-codex-high",
            "xhigh": "gpt-5-3-codex-xhigh",
            "max": "gpt-5-3-codex-xhigh",
        },
    },
    "gpt-5-4": {
        "default": "gpt-5-4-medium",
        "aliases": {"gpt-5-4"},
        "levels": {
            "auto": "gpt-5-4-medium",
            "minimal": "gpt-5-4-low",
            "low": "gpt-5-4-low",
            "medium": "gpt-5-4-medium",
            "high": "gpt-5-4-high",
            "xhigh": "gpt-5-4-xhigh",
            "max": "gpt-5-4-xhigh",
        },
    },
}


def _canonicalize_versioned_model_name(model_name: str) -> str:
    canonical = re.sub(r"^gpt-5\.(\d)(.*)$", r"gpt-5-\1\2", model_name)
    canonical = re.sub(r"^claude-4\.(5|6)(.*)$", r"claude-4-\1\2", canonical)
    return canonical


def _build_reasoning_family_index() -> dict:
    index = {}
    for family_name, family_config in REASONING_MODEL_FAMILIES.items():
        aliases = set(family_config.get("aliases", set()))
        aliases.add(family_name)
        aliases.update(family_config.get("levels", {}).values())
        for alias in aliases:
            index[_canonicalize_versioned_model_name(alias)] = family_name
    return index


REASONING_MODEL_TO_FAMILY = _build_reasoning_family_index()


def normalize_reasoning_effort(reasoning_effort: str | None) -> str | None:
    normalized = (reasoning_effort or "").strip().lower()
    if not normalized:
        return None
    if normalized not in RECOGNIZED_REASONING_EFFORTS:
        return None
    return normalized


def normalize_model_name(model_name: str) -> str:
    normalized = (model_name or "").strip().lower()
    if not normalized:
        return "auto"
    normalized = MODEL_ALIASES.get(normalized, normalized)
    return _canonicalize_versioned_model_name(normalized)


def resolve_request_model(model_name: str, reasoning_effort: str | None = None) -> str:
    """
    Resolve an incoming OpenAI-compatible model name to a concrete Warp model id.

    When `reasoning_effort` is present, prefer the closest known reasoning variant
    for that model family. This is needed for clients like Claude Code / Codex via
    CLIProxyAPI, which express thinking intent as `reasoning_effort` instead of
    directly naming Warp's concrete upstream variant ids.
    """
    normalized_model = normalize_model_name(model_name)
    normalized_effort = normalize_reasoning_effort(reasoning_effort)
    family_name = REASONING_MODEL_TO_FAMILY.get(normalized_model)

    if normalized_effort and family_name:
        family = REASONING_MODEL_FAMILIES[family_name]
        return family.get("levels", {}).get(normalized_effort) or family.get("default") or normalized_model

    if normalized_model in MODEL_METADATA:
        return normalized_model

    if family_name:
        family = REASONING_MODEL_FAMILIES[family_name]
        return family.get("default") or normalized_model

    return normalized_model or "auto"


def get_model_config(model_name: str) -> dict:
    """
    Map the requested model id to Warp's base model selection.

    New upstream ids are passed through directly so model support does not
    silently lag behind the local catalog snapshot.
    """
    base_model = resolve_request_model(model_name)
    return {
        "base": base_model or "auto",
        "base_model": base_model or "auto",
        "planning": "o3",
        "coding": "auto",
    }


def get_warp_models():
    """Get the latest known Warp model catalog snapshot."""
    catalog = {}
    for category_name, category_config in CATEGORY_MODELS.items():
        models = []
        for model_id in category_config["model_ids"]:
            metadata = MODEL_METADATA[model_id]
            models.append(
                {
                    "id": model_id,
                    "display_name": metadata["display_name"],
                    "description": metadata["description"],
                    "vision_supported": metadata["vision_supported"],
                    "usage_multiplier": 1,
                    "category": category_name,
                    "provider": metadata["provider"],
                    "reasoning_level": metadata["reasoning_level"],
                }
            )
        catalog[category_name] = {
            "default": category_config["default"],
            "models": models,
        }
    return catalog


def get_all_unique_models():
    """Get all unique models across categories for OpenAI-compatible listing."""
    try:
        created_at = int(time.time())
        unique_models = {}

        for category_data in get_warp_models().values():
            for model in category_data["models"]:
                model_id = model["id"]
                if model_id not in unique_models:
                    provider = model.get("provider", "UNKNOWN")
                    unique_models[model_id] = {
                        "id": model_id,
                        "object": "model",
                        "created": created_at,
                        "owned_by": PROVIDER_OWNERS.get(provider, "warp"),
                        "display_name": model["display_name"],
                        "description": model["description"] or model["display_name"],
                        "vision_supported": model["vision_supported"],
                        "usage_multiplier": model["usage_multiplier"],
                        "categories": [model["category"]],
                    }
                elif model["category"] not in unique_models[model_id]["categories"]:
                    unique_models[model_id]["categories"].append(model["category"])

        return list(unique_models.values())
    except Exception:
        return [
            {
                "id": "auto",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "warp",
                "display_name": "auto (responsive)",
                "description": "Auto-select best model",
            }
        ]
