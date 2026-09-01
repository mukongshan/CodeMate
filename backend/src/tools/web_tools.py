"""联网工具：公共网页搜索和网页抓取。

实现参考 deepseek-harness 的 ``web_search`` / ``web_fetch`` 工具，但保持
CodeMate 的零新增运行时依赖：HTTP 使用标准库，输出和响应大小有硬上限，
并拒绝解析到本机/内网地址的 URL，避免把联网能力变成 SSRF 通道。
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .base import Tool, ToolResult

DEFAULT_FETCH_TIMEOUT = 20
DEFAULT_SEARCH_TIMEOUT = 20
MAX_FETCH_BYTES = 2 * 1024 * 1024
MAX_FETCH_CHARS = 100_000
MAX_SEARCH_BYTES = 1 * 1024 * 1024
MAX_SEARCH_RESULTS = 8
MAX_REDIRECTS = 5
DEFAULT_SEARCH_PROVIDER = "bocha"
DEFAULT_BOCHA_BASE_URL = "https://api.bochaai.com"
DEFAULT_BOCHA_FRESHNESS = "noLimit"
DEFAULT_VOLCENGINE_SEARCH_ENDPOINT = (
    "https://open.feedcoopapi.com/search_api/global_search"
)
DEFAULT_VOLCENGINE_MAX_SNIPPET_LENGTH = 1000
USER_AGENT = "CodeMate/1.0"


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, msg, headers, new_url):
        return None


_OPENER = build_opener(_NoRedirectHandler())


def _public_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "URL 格式无效"
    if parsed.scheme not in {"http", "https"}:
        return False, "只允许访问 http 或 https URL"
    if not parsed.hostname:
        return False, "URL 缺少主机名"
    if parsed.username or parsed.password:
        return False, "不允许携带 URL 用户名或密码"
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(
                parsed.hostname, parsed.port, type=socket.SOCK_STREAM
            )
        }
    except (OSError, ValueError):
        return False, f"无法解析主机名: {parsed.hostname}"
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, "为避免访问内网或本机地址，已拒绝该 URL"
    return True, ""


def _decode_body(raw: bytes, content_type: str = "") -> str:
    charset = None
    match = re.search(r"charset\s*=\s*[\"']?([\w.-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    for encoding in (charset, "utf-8", "gb18030", "latin-1"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _html_to_text(source: str) -> str:
    class TextParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []
            self.skip_depth = 0

        def handle_starttag(self, tag: str, attrs) -> None:
            tag = tag.lower()
            if tag in {"script", "style", "noscript", "svg"}:
                self.skip_depth += 1
            elif tag in {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4"}:
                self.parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            tag = tag.lower()
            if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
                self.skip_depth -= 1
            elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
                self.parts.append("\n")

        def handle_data(self, data: str) -> None:
            if not self.skip_depth:
                self.parts.append(data)

    parser = TextParser()
    try:
        parser.feed(source)
        text = "".join(parser.parts)
    except Exception:  # malformed HTML should still produce bounded text
        text = source
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _read_url(url: str, timeout: int, max_bytes: int) -> dict:
    current = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        valid, reason = _public_url(current)
        if not valid:
            return {"error": reason}
        request = Request(
            current,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,text/plain,application/json;q=0.9,*/*;q=0.5",
            },
        )
        try:
            response = _OPENER.open(request, timeout=timeout)
        except HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                if redirect_count == MAX_REDIRECTS:
                    return {"error": f"重定向次数超过上限 {MAX_REDIRECTS}"}
                current = urljoin(current, exc.headers["Location"])
                continue
            return {"error": f"HTTP 请求失败: {exc.code} {exc.reason}"}
        except (URLError, OSError, TimeoutError) as exc:
            detail = exc.reason if isinstance(exc, URLError) else exc
            return {"error": f"网络请求失败: {detail}"}

        try:
            raw = response.read(max_bytes + 1)
            truncated = len(raw) > max_bytes
            raw = raw[:max_bytes]
            content_type = response.headers.get("Content-Type", "")
            return {
                "url": response.geturl(),
                "status": response.status,
                "content_type": content_type,
                "body": _decode_body(raw, content_type),
                "truncated": truncated,
            }
        finally:
            response.close()
    return {"error": "网络请求失败"}


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    site_name: str = ""
    published_at: str = ""


@dataclass(frozen=True)
class SearchResponse:
    results: list[SearchResult]
    total_estimated_matches: int | None = None
    log_id: str = ""


class SearchProviderError(RuntimeError):
    pass


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int) -> SearchResponse: ...


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def _read_json_response(response, max_bytes: int = MAX_SEARCH_BYTES) -> dict:
    raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise SearchProviderError(f"搜索服务响应超过 {max_bytes} 字节上限")
    content_type = response.headers.get("Content-Type", "")
    try:
        payload = json.loads(_decode_body(raw, content_type))
    except json.JSONDecodeError as exc:
        raise SearchProviderError("搜索服务返回了无效 JSON") from exc
    if not isinstance(payload, dict):
        raise SearchProviderError("搜索服务返回的数据结构无效")
    return payload


class BochaSearchProvider:
    name = "bocha"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        freshness: str | None = None,
        summary: bool | None = None,
        timeout: int = DEFAULT_SEARCH_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.freshness = freshness
        self.summary = summary
        self.timeout = timeout

    def _api_key(self) -> str:
        api_key = (self.api_key or os.getenv("BOCHA_API_KEY", "")).strip()
        if not api_key:
            raise SearchProviderError("未配置博查搜索 API Key（BOCHA_API_KEY）")
        return api_key

    def _endpoint(self) -> str:
        base_url = (
            self.base_url
            or os.getenv("BOCHA_BASE_URL", "")
            or DEFAULT_BOCHA_BASE_URL
        ).strip().rstrip("/")
        if base_url.endswith("/v1/web-search"):
            return base_url
        return f"{base_url}/v1/web-search"

    def _freshness(self) -> str:
        return (
            self.freshness
            or os.getenv("BOCHA_SEARCH_FRESHNESS", "")
            or DEFAULT_BOCHA_FRESHNESS
        ).strip()

    def _summary_enabled(self) -> bool:
        if self.summary is not None:
            return self.summary
        value = os.getenv("BOCHA_SEARCH_SUMMARY", "true").strip().lower()
        return value not in {"0", "false", "no", "off"}

    def search(self, query: str, limit: int) -> SearchResponse:
        api_key = self._api_key()
        endpoint = self._endpoint()
        valid, reason = _public_url(endpoint)
        if not valid:
            raise SearchProviderError(f"博查搜索服务地址不可用: {reason}")

        request = Request(
            endpoint,
            data=json.dumps(
                {
                    "query": query,
                    "freshness": self._freshness(),
                    "summary": self._summary_enabled(),
                    "count": limit,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        response = None
        try:
            response = _OPENER.open(request, timeout=self.timeout)
            payload = _read_json_response(response)
        except HTTPError as exc:
            try:
                try:
                    payload = _read_json_response(exc)
                    detail = _clean_text(
                        payload.get("msg") or payload.get("message")
                    )
                except SearchProviderError:
                    detail = ""
            finally:
                exc.close()
            suffix = f": {detail}" if detail else ""
            raise SearchProviderError(f"博查搜索请求失败: HTTP {exc.code}{suffix}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            detail = exc.reason if isinstance(exc, URLError) else exc
            raise SearchProviderError(f"博查搜索网络请求失败: {detail}") from exc
        finally:
            if response is not None:
                response.close()

        code = payload.get("code")
        if str(code) != "200":
            message = _clean_text(payload.get("msg") or payload.get("message"))
            detail = f": {message}" if message else ""
            raise SearchProviderError(f"博查搜索返回错误代码 {code}{detail}")

        data = payload.get("data")
        data = data if isinstance(data, dict) else {}
        web_pages = data.get("webPages")
        web_pages = web_pages if isinstance(web_pages, dict) else {}
        values = web_pages.get("value")
        values = values if isinstance(values, list) else []

        results: list[SearchResult] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            url = _clean_text(item.get("url"))
            if not url:
                continue
            results.append(
                SearchResult(
                    title=_clean_text(item.get("name")) or url,
                    url=url,
                    snippet=_clean_text(item.get("summary") or item.get("snippet")),
                    site_name=_clean_text(item.get("siteName")),
                    published_at=_clean_text(item.get("datePublished")),
                )
            )
            if len(results) >= limit:
                break

        total = web_pages.get("totalEstimatedMatches")
        if not isinstance(total, int):
            total = None
        return SearchResponse(
            results=results,
            total_estimated_matches=total,
            log_id=_clean_text(payload.get("log_id") or data.get("log_id")),
        )


class VolcengineSearchProvider:
    name = "volcengine"

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        max_snippet_length: int | None = None,
        icp_host_only: bool | None = None,
        timeout: int = DEFAULT_SEARCH_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.max_snippet_length = max_snippet_length
        self.icp_host_only = icp_host_only
        self.timeout = timeout

    def _api_key(self) -> str:
        api_key = (
            self.api_key
            or os.getenv("VOLCENGINE_SEARCH_API_KEY", "")
            or os.getenv("VOLCENGINE_API_KEY", "")
        ).strip()
        if not api_key:
            raise SearchProviderError(
                "未配置火山引擎搜索 API Key（VOLCENGINE_SEARCH_API_KEY）"
            )
        return api_key

    def _endpoint(self) -> str:
        return (
            self.endpoint
            or os.getenv("VOLCENGINE_SEARCH_ENDPOINT", "")
            or DEFAULT_VOLCENGINE_SEARCH_ENDPOINT
        ).strip()

    def _max_snippet_length(self) -> int:
        if self.max_snippet_length is not None:
            value = self.max_snippet_length
        else:
            raw = os.getenv("VOLCENGINE_SEARCH_MAX_SNIPPET_LENGTH", "").strip()
            if not raw:
                return DEFAULT_VOLCENGINE_MAX_SNIPPET_LENGTH
            try:
                value = int(raw)
            except ValueError as exc:
                raise SearchProviderError(
                    "VOLCENGINE_SEARCH_MAX_SNIPPET_LENGTH 必须是整数"
                ) from exc
        if not 1 <= value <= 3000:
            raise SearchProviderError(
                "VOLCENGINE_SEARCH_MAX_SNIPPET_LENGTH 必须在 1 到 3000 之间"
            )
        return value

    def _icp_host_only(self) -> bool:
        if self.icp_host_only is not None:
            return self.icp_host_only
        value = os.getenv("VOLCENGINE_SEARCH_ICP_HOST_ONLY", "false")
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _error_detail(payload: dict) -> str:
        metadata = payload.get("ResponseMetadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        error = metadata.get("Error")
        if not isinstance(error, dict):
            return ""
        code = _clean_text(error.get("Code") or error.get("CodeN"))
        message = _clean_text(error.get("Message"))
        return ": ".join(part for part in (code, message) if part)

    def search(self, query: str, limit: int) -> SearchResponse:
        api_key = self._api_key()
        endpoint = self._endpoint()
        valid, reason = _public_url(endpoint)
        if not valid:
            raise SearchProviderError(f"火山引擎搜索服务地址不可用: {reason}")

        request = Request(
            endpoint,
            data=json.dumps(
                {
                    "Query": query,
                    "SearchType": "web",
                    "DocCount": limit,
                    "MaxSnippetLength": self._max_snippet_length(),
                    "Filter": {"IcpHostOnly": self._icp_host_only()},
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        response = None
        try:
            response = _OPENER.open(request, timeout=self.timeout)
            payload = _read_json_response(response)
        except HTTPError as exc:
            try:
                try:
                    payload = _read_json_response(exc)
                    detail = self._error_detail(payload)
                except SearchProviderError:
                    detail = ""
            finally:
                exc.close()
            suffix = f": {detail}" if detail else ""
            raise SearchProviderError(
                f"火山引擎搜索请求失败: HTTP {exc.code}{suffix}"
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            detail = exc.reason if isinstance(exc, URLError) else exc
            raise SearchProviderError(
                f"火山引擎搜索网络请求失败: {detail}"
            ) from exc
        finally:
            if response is not None:
                response.close()

        metadata = payload.get("ResponseMetadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        error_detail = self._error_detail(payload)
        if error_detail:
            raise SearchProviderError(f"火山引擎搜索返回错误: {error_detail}")

        result = payload.get("Result")
        if not isinstance(result, dict):
            raise SearchProviderError("火山引擎搜索响应缺少 Result")
        error_code = result.get("ErrorCode", 0)
        if str(error_code) != "0":
            message = _clean_text(result.get("ErrorMsg"))
            detail = f": {message}" if message else ""
            raise SearchProviderError(
                f"火山引擎搜索返回错误代码 {error_code}{detail}"
            )

        documents = result.get("Documents")
        documents = documents if isinstance(documents, list) else []
        results: list[SearchResult] = []
        for document in documents:
            if not isinstance(document, dict):
                continue
            url = _clean_text(document.get("Url"))
            if not url:
                continue
            snippets = document.get("Snippet")
            snippets = snippets if isinstance(snippets, list) else []
            snippet = " ".join(
                _clean_text(item.get("Text"))
                for item in snippets
                if isinstance(item, dict)
                and item.get("Type") == "text"
                and item.get("Text")
            )
            document_info = document.get("DocumentInfo")
            document_info = (
                document_info if isinstance(document_info, dict) else {}
            )
            host_info = document.get("HostInfo")
            host_info = host_info if isinstance(host_info, dict) else {}
            results.append(
                SearchResult(
                    title=_clean_text(document.get("Title")) or url,
                    url=url,
                    snippet=_clean_text(snippet),
                    site_name=_clean_text(host_info.get("Hostname")),
                    published_at=_clean_text(document_info.get("PublishTime")),
                )
            )
            if len(results) >= limit:
                break

        total = result.get("TotalDocCount")
        if not isinstance(total, int):
            total = None
        return SearchResponse(
            results=results,
            total_estimated_matches=total,
            log_id=_clean_text(metadata.get("RequestId")),
        )


def create_search_provider(name: str | None = None) -> SearchProvider:
    provider_name = (
        name or os.getenv("WEB_SEARCH_PROVIDER", "") or DEFAULT_SEARCH_PROVIDER
    ).strip().lower()
    if provider_name == "bocha":
        return BochaSearchProvider()
    if provider_name in {"volcengine", "doubao"}:
        return VolcengineSearchProvider()
    raise SearchProviderError(f"不支持的搜索服务提供方: {provider_name}")


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "抓取公共 HTTP(S) 网页或文本资源，提取可读正文并限制输出大小。"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的公共 HTTP(S) URL"},
            "max_chars": {
                "type": "integer",
                "description": f"最多返回字符数，默认 {MAX_FETCH_CHARS}",
            },
        },
        "required": ["url"],
    }

    async def execute(
        self, url: str, max_chars: int = MAX_FETCH_CHARS
    ) -> ToolResult:
        if not url or not url.strip():
            return ToolResult.error("url 不能为空")
        max_chars = max(1, min(int(max_chars), MAX_FETCH_CHARS))
        result = await asyncio.to_thread(
            _read_url, url.strip(), DEFAULT_FETCH_TIMEOUT, MAX_FETCH_BYTES
        )
        if "error" in result:
            return ToolResult.error(
                result["error"],
                suggestions=[
                    "确认 URL 是公共 http(s) 地址",
                    "如只需查找资料，优先使用 web_search",
                ],
            )
        content = result["body"]
        if "html" in result["content_type"].lower() or re.search(
            r"<\s*(html|body|main|article)\b", content, re.I
        ):
            content = _html_to_text(content)
        truncated = result["truncated"] or len(content) > max_chars
        content = content[:max_chars]
        body = f"URL: {result['url']}\nHTTP {result['status']}\n\n{content or '（无可读正文）'}"
        return ToolResult.ok(
            body,
            url=result["url"],
            status=result["status"],
            truncated=truncated,
        )


class WebSearchTool(Tool):
    name = "web_search"
    description = "通过已配置的搜索服务提供方检索当前网页信息，返回标题、URL 和摘要。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词或问题"},
            "limit": {
                "type": "integer",
                "description": f"返回结果数，默认 {MAX_SEARCH_RESULTS}，最多 {MAX_SEARCH_RESULTS}",
            },
        },
        "required": ["query"],
    }

    def __init__(self, provider: SearchProvider | None = None) -> None:
        self.provider = provider

    async def execute(
        self, query: str, limit: int = MAX_SEARCH_RESULTS
    ) -> ToolResult:
        if not query or not query.strip():
            return ToolResult.error("query 不能为空")
        limit = max(1, min(int(limit), MAX_SEARCH_RESULTS))
        provider = self.provider
        try:
            provider = provider or create_search_provider()
            response = await asyncio.to_thread(provider.search, query.strip(), limit)
        except SearchProviderError as exc:
            return ToolResult.error(
                str(exc),
                suggestions=[
                    "确认 WEB_SEARCH_PROVIDER 与对应搜索 API Key 已配置",
                    "确认搜索服务地址可从当前网络访问",
                ],
                provider=getattr(provider, "name", None),
            )
        if not response.results:
            return ToolResult.ok(
                "没有找到搜索结果",
                query=query.strip(),
                total=0,
                provider=provider.name,
                total_estimated_matches=response.total_estimated_matches,
                log_id=response.log_id,
            )
        lines = [f"搜索：{query.strip()}（{len(response.results)} 条）"]
        for index, item in enumerate(response.results, 1):
            lines.append(
                f"\n{index}. {item.title}\nURL: {item.url}\n摘要: {item.snippet or '无摘要'}"
            )
        return ToolResult.ok(
            "\n".join(lines),
            query=query.strip(),
            total=len(response.results),
            provider=provider.name,
            total_estimated_matches=response.total_estimated_matches,
            log_id=response.log_id,
        )
