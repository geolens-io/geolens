"""Tests for XML tool call parser."""

from app.ai.tool_call_parser import parse_xml_tool_calls


class TestParseXmlToolCalls:
    """Tests for parse_xml_tool_calls."""

    def test_single_tool_call(self):
        text = "<function=set_label><parameter=layer_id>abc</parameter></function>"
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert calls[0] == ("set_label", {"layer_id": "abc"})
        assert cleaned == ""

    def test_multiple_tool_calls(self):
        text = (
            "<function=set_label><parameter=layer_id>abc</parameter></function>"
            "<function=set_color><parameter=color>#ff0000</parameter></function>"
        )
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 2
        assert calls[0] == ("set_label", {"layer_id": "abc"})
        assert calls[1] == ("set_color", {"color": "#ff0000"})

    def test_multiple_parameters(self):
        text = "<function=set_style><parameter=color>#ff0000</parameter><parameter=opacity>0.8</parameter><parameter=width>3</parameter></function>"
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert calls[0][1] == {"color": "#ff0000", "opacity": 0.8, "width": 3}

    def test_whitespace_between_tags(self):
        text = (
            "<function=set_label>\n"
            "  <parameter=layer_id>abc</parameter>\n"
            "  <parameter=name>My Layer</parameter>\n"
            "</function>"
        )
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert calls[0][1]["layer_id"] == "abc"
        assert calls[0][1]["name"] == "My Layer"

    # --- Value coercion ---

    def test_coerce_int(self):
        text = "<function=set_style><parameter=font_size>10</parameter></function>"
        calls, _ = parse_xml_tool_calls(text)
        assert calls[0][1]["font_size"] == 10
        assert isinstance(calls[0][1]["font_size"], int)

    def test_coerce_float(self):
        text = "<function=set_style><parameter=opacity>0.5</parameter></function>"
        calls, _ = parse_xml_tool_calls(text)
        assert calls[0][1]["opacity"] == 0.5
        assert isinstance(calls[0][1]["opacity"], float)

    def test_coerce_bool_true(self):
        text = "<function=toggle_visibility><parameter=visible>true</parameter></function>"
        calls, _ = parse_xml_tool_calls(text)
        assert calls[0][1]["visible"] is True

    def test_coerce_bool_false(self):
        text = "<function=toggle_visibility><parameter=visible>False</parameter></function>"
        calls, _ = parse_xml_tool_calls(text)
        assert calls[0][1]["visible"] is False

    def test_coerce_bool_uppercase(self):
        text = "<function=toggle_visibility><parameter=a>TRUE</parameter><parameter=b>FALSE</parameter></function>"
        calls, _ = parse_xml_tool_calls(text)
        assert calls[0][1]["a"] is True
        assert calls[0][1]["b"] is False

    def test_string_stays_string(self):
        text = "<function=set_style><parameter=text_color>#333</parameter></function>"
        calls, _ = parse_xml_tool_calls(text)
        assert calls[0][1]["text_color"] == "#333"
        assert isinstance(calls[0][1]["text_color"], str)

    def test_value_whitespace_stripped(self):
        text = "<function=set_label><parameter=layer_id>  abc  </parameter></function>"
        calls, _ = parse_xml_tool_calls(text)
        assert calls[0][1]["layer_id"] == "abc"

    # --- Cleaned text ---

    def test_no_tool_calls(self):
        text = "Here is a plain response with no tool calls."
        calls, cleaned = parse_xml_tool_calls(text)
        assert calls == []
        assert cleaned == text

    def test_cleaned_text_strips_function_blocks(self):
        text = (
            "I'll update the label now. "
            "<function=set_label><parameter=layer_id>abc</parameter></function>"
            " Done!"
        )
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert cleaned == "I'll update the label now.  Done!"

    def test_cleaned_text_is_trimmed(self):
        text = "  \n <function=set_label><parameter=layer_id>abc</parameter></function>  \n "
        calls, cleaned = parse_xml_tool_calls(text)
        assert cleaned == ""

    def test_empty_string(self):
        calls, cleaned = parse_xml_tool_calls("")
        assert calls == []
        assert cleaned == ""

    # --- Wrapper tag stripping ---

    def test_tool_call_wrapper_qwen_style(self):
        """Qwen wraps <function> blocks in <tool_call>...</tool_call>."""
        text = (
            "I'll style the layer.\n\n"
            "<tool_call>\n"
            "<function=set_style><parameter=layer_id>abc</parameter></function>\n"
            "</tool_call>"
        )
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert calls[0] == ("set_style", {"layer_id": "abc"})
        assert "tool_call" not in cleaned.lower()
        assert cleaned == "I'll style the layer."

    def test_tool_call_wrapper_llama_pipe_style(self):
        """Llama-style <|tool_call|>...<|/tool_call|> delimiters."""
        text = (
            "Setting filter.\n"
            "<|tool_call|>\n"
            "<function=set_filter><parameter=layer_id>x</parameter></function>\n"
            "<|/tool_call|>"
        )
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert calls[0] == ("set_filter", {"layer_id": "x"})
        assert "tool_call" not in cleaned.lower()
        assert cleaned == "Setting filter."

    def test_tool_call_wrapper_hyphen_style(self):
        """<tool-call>...<function>...</function></tool-call> variant."""
        text = (
            "<tool-call>"
            "<function=set_label><parameter=layer_id>z</parameter></function>"
            "</tool-call>"
        )
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert cleaned == ""

    def test_tool_call_wrapper_without_function(self):
        """Bare wrapper with no inner <function> block — strip wrapper, keep text."""
        text = "<tool_call>some text</tool_call>"
        calls, cleaned = parse_xml_tool_calls(text)
        assert calls == []
        assert cleaned == "some text"

    def test_tool_call_wrapper_case_insensitive(self):
        text = (
            "Thinking.\n"
            "<Tool_Call>\n"
            "<function=set_label><parameter=layer_id>x</parameter></function>\n"
            "</Tool_Call>"
        )
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert "Tool_Call" not in cleaned

    # --- Fast path ---

    def test_fast_path_skips_regex_for_plain_text(self):
        """Plain text without <function triggers fast path — no regex overhead."""
        text = "The layer has 3 features in the Conservation Priority Areas."
        calls, cleaned = parse_xml_tool_calls(text)
        assert calls == []
        assert cleaned == text

    def test_fast_path_still_strips_orphaned_wrappers(self):
        """Orphaned wrapper tags (no <function>) are stripped even on fast path."""
        text = "Done.\n</tool_call>"
        calls, cleaned = parse_xml_tool_calls(text)
        assert calls == []
        assert cleaned == "Done."
