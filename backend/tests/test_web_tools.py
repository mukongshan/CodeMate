from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.tools.file_tools import ListDirectoryTool
from src.tools.registry import ToolRegistry
from src.tools.web_tools import WebFetchTool, WebSearchTool, _html_to_text


def _response(body: str, content_type: str = "text/html; charset=utf-8") -> MagicMock:
    response = MagicMock()
    response.read.side_effect = lambda size=-1: body.encode("utf-8")
    response.geturl.return_value = "https://example.com/page"
    response.status = 200
    response.headers = {"Content-Type": content_type}
    return response


class TestWebTools:
    @pytest.mark.asyncio
    async def test_fetch_converts_html_and_truncates(self):
        response = _response(
            "<html><script>ignore()</script><h1>Title</h1>"
            "<p>Hello <b>world</b></p></html>"
        )
        with patch(
            "src.tools.web_tools._public_url", return_value=(True, "")
        ), patch("src.tools.web_tools._OPENER.open", return_value=response):
            result = await WebFetchTool().execute(
                "https://example.com/page", max_chars=10
            )

        assert not result.is_error
        assert "Title" in result.content
        assert "ignore" not in result.content
        assert result.metadata["truncated"] is True

    @pytest.mark.asyncio
    async def test_search_returns_structured_results(self):
        response = _response(
            '<a class="result__a" href="https://example.com/a">One</a>'
            '<div class="result__snippet">First result</div>'
            '<a class="result__a" href="https://example.com/b">Two</a>'
            '<div class="result__snippet">Second result</div>'
        )
        with patch(
            "src.tools.web_tools._public_url", return_value=(True, "")
        ), patch("src.tools.web_tools._OPENER.open", return_value=response):
            result = await WebSearchTool().execute("codemate", limit=1)

        assert not result.is_error
        assert "One" in result.content
        assert "https://example.com/a" in result.content
        assert result.metadata["total"] == 1

    @pytest.mark.asyncio
    async def test_fetch_rejects_non_public_url(self):
        result = await WebFetchTool().execute("file:///etc/passwd")
        assert result.is_error
        assert "http" in result.content


class TestListDirectoryTool:
    @pytest.mark.asyncio
    async def test_lists_direct_children_without_hidden_by_default(self, tmp_path):
        (tmp_path / "folder").mkdir()
        (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
        (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")

        result = await ListDirectoryTool(tmp_path).execute()

        assert not result.is_error
        assert "folder" in result.content
        assert "file.txt" in result.content
        assert ".hidden" not in result.content


def test_default_registries_include_common_tools(tmp_path):
    registry = ToolRegistry.default(tmp_path)
    readonly = ToolRegistry.readonly(tmp_path)

    for name in {"list_directory", "web_search", "web_fetch"}:
        assert registry.has_tool(name)
        assert readonly.has_tool(name)


def test_html_to_text_removes_non_content_elements():
    assert _html_to_text("<style>x{}</style><p>A</p><p>B</p>") == "A\nB"
