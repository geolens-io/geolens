"""Parse XML-like tool calls from LLM text output.

Some OpenAI-compatible providers (Ollama, LM Studio, vLLM) emit tool calls
as XML-like text instead of using the structured function-calling API.
This module detects and parses those patterns so they can be executed
through the existing tool pipeline.
"""

import re

_FUNCTION_RE = re.compile(r"<function=(\w+)>(.*?)</function>", re.DOTALL)
_PARAMETER_RE = re.compile(r"<parameter=(\w+)>(.*?)</parameter>", re.DOTALL)
# Wrapper tags some models emit around function blocks
_TOOL_CALL_WRAPPER_RE = re.compile(r"</?tool_call>", re.IGNORECASE)


def _coerce_value(value: str) -> int | float | str:
    """Coerce a string value to int, float, or leave as str."""
    v = value.strip()
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def parse_xml_tool_calls(text: str) -> tuple[list[tuple[str, dict]], str]:
    """Parse XML-like tool calls from LLM text output.

    Returns (tool_calls, cleaned_text) where:
    - tool_calls: list of (tool_name, tool_input_dict) tuples
    - cleaned_text: original text with <function>...</function> blocks removed, trimmed
    """
    tool_calls: list[tuple[str, dict]] = []

    for fn_match in _FUNCTION_RE.finditer(text):
        fn_name = fn_match.group(1)
        fn_body = fn_match.group(2)

        params: dict = {}
        for param_match in _PARAMETER_RE.finditer(fn_body):
            param_name = param_match.group(1)
            param_value = param_match.group(2)
            params[param_name] = _coerce_value(param_value)

        tool_calls.append((fn_name, params))

    cleaned = _FUNCTION_RE.sub("", text)
    # Strip wrapper tags (e.g. <tool_call> / </tool_call>) that some models
    # emit around function blocks
    cleaned = _TOOL_CALL_WRAPPER_RE.sub("", cleaned).strip()
    return tool_calls, cleaned
