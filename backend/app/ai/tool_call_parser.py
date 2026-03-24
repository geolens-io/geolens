"""Parse XML-like tool calls from LLM text output.

Some OpenAI-compatible providers (Ollama, LM Studio, vLLM) emit tool calls
as XML-like text instead of using the structured function-calling API.
This module detects and parses those patterns so they can be executed
through the existing tool pipeline.

Known formats:
  - Qwen:   <tool_call><function=name>...</function></tool_call>
  - Llama:  <|tool_call|><function=name>...</function><|/tool_call|>
  - Others: <tool-call>...<function=name>...</function></tool-call>
"""

import re

_FUNCTION_RE = re.compile(r"<function=(\w+)>(.*?)</function>", re.DOTALL)
_PARAMETER_RE = re.compile(r"<parameter=(\w+)>(.*?)</parameter>", re.DOTALL)

# Wrapper tags various models emit around function blocks.
# Matches: <tool_call>, </tool_call>, <|tool_call|>, <|/tool_call|>,
#          <tool-call>, </tool-call>, and case variants.
_TOOL_CALL_WRAPPER_RE = re.compile(
    r"<\|?/?tool[-_]call\|?>",
    re.IGNORECASE,
)


def _coerce_value(value: str) -> int | float | bool | str:
    """Coerce a string value to int, float, bool, or leave as str."""
    v = value.strip()

    # Boolean
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False

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
    - cleaned_text: original text with XML tool blocks removed, trimmed

    Fast-path: if the text contains no ``<function`` marker, returns
    immediately without running any regex.
    """
    # Fast path — skip regex scan when there are no XML tool calls
    if "<function" not in text.lower():
        cleaned = _TOOL_CALL_WRAPPER_RE.sub("", text).strip()
        return [], cleaned

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
    cleaned = _TOOL_CALL_WRAPPER_RE.sub("", cleaned).strip()
    return tool_calls, cleaned
