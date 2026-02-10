"""Tests for agent tool definitions."""

from pam.agent.tools import ALL_TOOLS, SEARCH_KNOWLEDGE_TOOL


class TestToolDefinitions:
    def test_search_knowledge_tool_structure(self):
        tool = SEARCH_KNOWLEDGE_TOOL
        assert tool["name"] == "search_knowledge"
        assert "description" in tool
        assert "input_schema" in tool

        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "query" in schema["required"]

    def test_all_tools_is_list(self):
        assert isinstance(ALL_TOOLS, list)
        assert len(ALL_TOOLS) >= 1

    def test_all_tools_have_required_fields(self):
        for tool in ALL_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert isinstance(tool["name"], str)
            assert isinstance(tool["description"], str)
