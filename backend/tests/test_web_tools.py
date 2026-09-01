from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.tools.file_tools import ListDirectoryTool
from src.tools.registry import ToolRegistry
from src.tools.web_tools import (
    BochaSearchProvider,
    VolcengineSearchProvider,
    WebFetchTool,
    WebSearchTool,
    _html_to_text,
)


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
    async def test_search_uses_bocha_provider(self, monkeypatch):
        response = _response(
            json.dumps(
                {
                    "code": 200,
                    "msg": None,
                    "data": {
                        "webPages": {
                            "totalEstimatedMatches": 2,
                            "value": [
                                {
                                    "name": "One",
                                    "url": "https://example.com/a",
                                    "snippet": "Fallback snippet",
                                    "summary": "First result",
                                    "siteName": "Example",
                                    "datePublished": "2026-09-01",
                                },
                                {
                                    "name": "Two",
                                    "url": "https://example.com/b",
                                    "summary": "Second result",
                                },
                            ],
                        }
                    },
                    "log_id": "log-123",
                }
            ),
            "application/json; charset=utf-8",
        )
        monkeypatch.setenv("BOCHA_API_KEY", "test-key")
        with patch(
            "src.tools.web_tools._public_url", return_value=(True, "")
        ), patch(
            "src.tools.web_tools._OPENER.open", return_value=response
        ) as open_mock:
            result = await WebSearchTool(BochaSearchProvider()).execute(
                "codemate", limit=1
            )

        assert not result.is_error
        assert "One" in result.content
        assert "https://example.com/a" in result.content
        assert "First result" in result.content
        assert result.metadata["total"] == 1
        assert result.metadata["provider"] == "bocha"
        assert result.metadata["total_estimated_matches"] == 2
        assert result.metadata["log_id"] == "log-123"

        request = open_mock.call_args.args[0]
        assert request.full_url == "https://api.bochaai.com/v1/web-search"
        assert request.method == "POST"
        assert request.get_header("Authorization") == "Bearer test-key"
        assert json.loads(request.data) == {
            "query": "codemate",
            "freshness": "noLimit",
            "summary": True,
            "count": 1,
        }

    @pytest.mark.asyncio
    async def test_search_reports_missing_bocha_api_key(self, monkeypatch):
        monkeypatch.delenv("BOCHA_API_KEY", raising=False)
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)

        result = await WebSearchTool().execute("codemate")

        assert result.is_error
        assert "BOCHA_API_KEY" in result.content
        assert result.metadata["provider"] == "bocha"

    @pytest.mark.asyncio
    async def test_search_rejects_unknown_provider(self, monkeypatch):
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "unknown")

        result = await WebSearchTool().execute("codemate")

        assert result.is_error
        assert "不支持的搜索服务提供方" in result.content

    @pytest.mark.asyncio
    async def test_search_reports_provider_error(self, monkeypatch):
        response = _response(
            json.dumps({"code": 401, "msg": "invalid api key"}),
            "application/json",
        )
        monkeypatch.setenv("BOCHA_API_KEY", "bad-key")
        with patch(
            "src.tools.web_tools._public_url", return_value=(True, "")
        ), patch("src.tools.web_tools._OPENER.open", return_value=response):
            result = await WebSearchTool(BochaSearchProvider()).execute("codemate")

        assert result.is_error
        assert "401" in result.content
        assert "invalid api key" in result.content

    @pytest.mark.asyncio
    async def test_search_uses_volcengine_provider(self, monkeypatch):
        response = _response(
            json.dumps(
                {
                    "ResponseMetadata": {
                        "RequestId": "request-123",
                        "Action": "",
                        "Version": "",
                        "Service": "",
                        "Region": "",
                    },
                    "Result": {
                        "TotalDocCount": 12,
                        "Documents": [
                            {
                                "Rank": 0,
                                "Url": "https://example.com/volcengine",
                                "Title": "Volcengine Result",
                                "Snippet": [
                                    {"Type": "text", "Text": "First part"},
                                    {"Type": "image", "Image": {}},
                                    {"Type": "text", "Text": "Second part"},
                                ],
                                "DocumentInfo": {
                                    "Filetype": "webpage",
                                    "PublishTime": "2026-08-31",
                                },
                                "HostInfo": {"Hostname": "Example"},
                            }
                        ],
                        "ErrorCode": 0,
                        "ErrorMsg": "",
                    },
                }
            ),
            "application/json; charset=utf-8",
        )
        monkeypatch.setenv("VOLCENGINE_SEARCH_API_KEY", "test-volc-key")
        with patch(
            "src.tools.web_tools._public_url", return_value=(True, "")
        ), patch(
            "src.tools.web_tools._OPENER.open", return_value=response
        ) as open_mock:
            result = await WebSearchTool(VolcengineSearchProvider()).execute(
                "codemate", limit=1
            )

        assert not result.is_error
        assert "Volcengine Result" in result.content
        assert "First part Second part" in result.content
        assert result.metadata["provider"] == "volcengine"
        assert result.metadata["total_estimated_matches"] == 12
        assert result.metadata["log_id"] == "request-123"

        request = open_mock.call_args.args[0]
        assert request.full_url == (
            "https://open.feedcoopapi.com/search_api/global_search"
        )
        assert request.method == "POST"
        assert request.get_header("Authorization") == "Bearer test-volc-key"
        assert json.loads(request.data) == {
            "Query": "codemate",
            "SearchType": "web",
            "DocCount": 1,
            "MaxSnippetLength": 1000,
            "Filter": {"IcpHostOnly": False},
        }

    @pytest.mark.asyncio
    async def test_search_reports_missing_volcengine_api_key(self, monkeypatch):
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "volcengine")
        monkeypatch.delenv("VOLCENGINE_SEARCH_API_KEY", raising=False)
        monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)

        result = await WebSearchTool().execute("codemate")

        assert result.is_error
        assert "VOLCENGINE_SEARCH_API_KEY" in result.content
        assert result.metadata["provider"] == "volcengine"

    @pytest.mark.asyncio
    async def test_search_reports_volcengine_response_error(self, monkeypatch):
        response = _response(
            json.dumps(
                {
                    "ResponseMetadata": {
                        "RequestId": "request-error",
                        "Error": {
                            "CodeN": 700901,
                            "Code": "700901",
                            "Message": "APIKey invalid",
                        },
                    },
                    "Result": None,
                }
            ),
            "application/json",
        )
        monkeypatch.setenv("VOLCENGINE_SEARCH_API_KEY", "bad-volc-key")
        with patch(
            "src.tools.web_tools._public_url", return_value=(True, "")
        ), patch("src.tools.web_tools._OPENER.open", return_value=response):
            result = await WebSearchTool(VolcengineSearchProvider()).execute(
                "codemate"
            )

        assert result.is_error
        assert "700901" in result.content
        assert "APIKey invalid" in result.content

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
