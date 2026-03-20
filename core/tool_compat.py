#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tool-name compatibility helpers.

Warp can still emit internal/legacy tool ids even when custom client tools are
provided. Normalize those names so downstream executors see the canonical tool
names they actually expose.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


LEGACY_TOOL_NAME_ALIASES = {
    "agent": "Agent",
    "apply_file_diffs": "Edit",
    "bash": "Bash",
    "edit": "Edit",
    "edit_file": "Edit",
    "file_glob": "Glob",
    "file_glob_v2": "Glob",
    "glob": "Glob",
    "grep": "Grep",
    "read": "Read",
    "read_file": "Read",
    "read_files": "Read",
    "run_shell_command": "Bash",
    "search_codebase": "Grep",
    "task_output": "TaskOutput",
    "web_fetch": "WebFetch",
    "web_search": "WebSearch",
    "write": "Write",
    "write_file": "Write",
}


CANONICAL_TOOL_CASE = {
    "agent": "Agent",
    "bash": "Bash",
    "edit": "Edit",
    "glob": "Glob",
    "grep": "Grep",
    "read": "Read",
    "taskoutput": "TaskOutput",
    "webfetch": "WebFetch",
    "websearch": "WebSearch",
    "write": "Write",
}


DEFERRED_PAYLOAD_TOOL_NAMES = {
    "apply_file_diffs",
    "Bash",
    "Edit",
    "file_glob",
    "file_glob_v2",
    "Glob",
    "Grep",
    "grep",
    "Read",
    "read_files",
    "run_shell_command",
    "search_codebase",
}


def normalize_tool_name(name: Optional[str]) -> Optional[str]:
    if not name or not isinstance(name, str):
        return name

    canonical = LEGACY_TOOL_NAME_ALIASES.get(name, name)
    return CANONICAL_TOOL_CASE.get(canonical.replace("_", "").lower(), canonical)


def _maybe_parse_arguments(arguments: Any) -> Any:
    if not isinstance(arguments, str):
        return arguments
    try:
        return json.loads(arguments)
    except Exception:
        return arguments


def _coerce_file_path(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        for key in ("file_path", "path", "name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    if value is not None and hasattr(value, "name"):
        candidate = getattr(value, "name")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def normalize_tool_arguments(
    original_name: Optional[str],
    arguments: Any,
    normalized_name: Optional[str] = None,
) -> Any:
    normalized_name = normalized_name or normalize_tool_name(original_name)
    parsed_arguments = _maybe_parse_arguments(arguments)

    if not isinstance(parsed_arguments, dict):
        return parsed_arguments

    if original_name == "run_shell_command" or normalized_name == "Bash":
        normalized: Dict[str, Any] = {}
        if parsed_arguments.get("command"):
            normalized["command"] = parsed_arguments["command"]
        for key in ("description", "timeout", "run_in_background", "dangerouslyDisableSandbox"):
            if key in parsed_arguments:
                normalized[key] = parsed_arguments[key]
        return normalized

    if original_name in ("file_glob", "file_glob_v2") or normalized_name == "Glob":
        normalized = {}
        patterns = parsed_arguments.get("patterns")
        if isinstance(patterns, list) and patterns:
            normalized["pattern"] = patterns[0]
        elif parsed_arguments.get("pattern"):
            normalized["pattern"] = parsed_arguments["pattern"]
        path = parsed_arguments.get("search_dir") or parsed_arguments.get("path")
        if path:
            normalized["path"] = path
        return normalized

    if original_name in ("grep", "search_codebase") or normalized_name == "Grep":
        normalized = {}
        pattern = parsed_arguments.get("pattern")
        queries = parsed_arguments.get("queries")
        if not pattern and isinstance(queries, list):
            query_terms = [query for query in queries if isinstance(query, str) and query]
            if len(query_terms) == 1:
                pattern = query_terms[0]
            elif query_terms:
                pattern = "|".join(re.escape(query) for query in query_terms)
        if pattern:
            normalized["pattern"] = pattern
        for key in (
            "path",
            "glob",
            "output_mode",
            "-A",
            "-B",
            "-C",
            "-i",
            "-n",
            "context",
            "head_limit",
            "multiline",
            "offset",
        ):
            if key in parsed_arguments:
                normalized[key] = parsed_arguments[key]
        return normalized

    if original_name == "read_files" or normalized_name == "Read":
        normalized = {}
        file_path = _coerce_file_path(parsed_arguments.get("file_path")) or _coerce_file_path(parsed_arguments.get("path"))
        files = parsed_arguments.get("files") or parsed_arguments.get("paths")
        if not file_path and isinstance(files, list) and files:
            file_path = _coerce_file_path(files[0])
        if file_path:
            normalized["file_path"] = file_path
        for key in ("offset", "limit", "pages"):
            if key in parsed_arguments:
                normalized[key] = parsed_arguments[key]
        return normalized

    return parsed_arguments


def should_defer_tool_call(name: Optional[str], arguments: Any) -> bool:
    if not name:
        return False

    normalized_name = normalize_tool_name(name)
    if name not in DEFERRED_PAYLOAD_TOOL_NAMES and normalized_name not in DEFERRED_PAYLOAD_TOOL_NAMES:
        return False

    parsed_arguments = _maybe_parse_arguments(arguments)
    return isinstance(parsed_arguments, dict) and len(parsed_arguments) == 0


def normalize_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(tool_call, dict):
        return tool_call

    if isinstance(tool_call.get("function"), dict):
        function = tool_call["function"]
        original_name = function.get("name")
        normalized_name = normalize_tool_name(original_name)
        normalized_arguments = normalize_tool_arguments(
            original_name,
            function.get("arguments"),
            normalized_name,
        )
        serialized_arguments = (
            normalized_arguments
            if isinstance(normalized_arguments, str)
            else json.dumps(normalized_arguments, ensure_ascii=False)
        )
        if normalized_name == original_name and serialized_arguments == function.get("arguments"):
            return tool_call

        normalized = dict(tool_call)
        normalized_function = dict(function)
        normalized_function["name"] = normalized_name
        normalized_function["arguments"] = serialized_arguments
        normalized["function"] = normalized_function
        return normalized

    normalized_name = normalize_tool_name(tool_call.get("name"))
    if normalized_name == tool_call.get("name"):
        return tool_call

    normalized = dict(tool_call)
    normalized["name"] = normalized_name
    return normalized


def normalize_tool_calls(tool_calls: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not tool_calls:
        return []
    return [normalize_tool_call(tool_call) for tool_call in tool_calls]
