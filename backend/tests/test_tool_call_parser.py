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

    def test_numeric_coercion_int(self):
        text = "<function=set_style><parameter=font_size>10</parameter></function>"
        calls, cleaned = parse_xml_tool_calls(text)
        assert calls[0][1]["font_size"] == 10
        assert isinstance(calls[0][1]["font_size"], int)

    def test_numeric_coercion_float(self):
        text = "<function=set_style><parameter=opacity>0.5</parameter></function>"
        calls, cleaned = parse_xml_tool_calls(text)
        assert calls[0][1]["opacity"] == 0.5
        assert isinstance(calls[0][1]["opacity"], float)

    def test_string_values_stay_strings(self):
        text = "<function=set_style><parameter=text_color>#333</parameter></function>"
        calls, cleaned = parse_xml_tool_calls(text)
        assert calls[0][1]["text_color"] == "#333"
        assert isinstance(calls[0][1]["text_color"], str)

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

    def test_whitespace_between_tags(self):
        text = (
            "<function=set_label>\n"
            "  <parameter=layer_id>abc</parameter>\n"
            "  <parameter=name>My Layer</parameter>\n"
            "</function>"
        )
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert calls[0][0] == "set_label"
        assert calls[0][1]["layer_id"] == "abc"
        assert calls[0][1]["name"] == "My Layer"

    def test_multiple_parameters(self):
        text = "<function=set_style><parameter=color>#ff0000</parameter><parameter=opacity>0.8</parameter><parameter=width>3</parameter></function>"
        calls, cleaned = parse_xml_tool_calls(text)
        assert len(calls) == 1
        assert calls[0][1] == {"color": "#ff0000", "opacity": 0.8, "width": 3}

    def test_cleaned_text_is_trimmed(self):
        text = "  \n <function=set_label><parameter=layer_id>abc</parameter></function>  \n "
        calls, cleaned = parse_xml_tool_calls(text)
        assert cleaned == ""

    def test_empty_string(self):
        calls, cleaned = parse_xml_tool_calls("")
        assert calls == []
        assert cleaned == ""

    def test_value_whitespace_stripped(self):
        text = "<function=set_label><parameter=layer_id>  abc  </parameter></function>"
        calls, cleaned = parse_xml_tool_calls(text)
        assert calls[0][1]["layer_id"] == "abc"
