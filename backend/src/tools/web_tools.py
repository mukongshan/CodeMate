"""联网工具：公共网页搜索和网页抓取。

实现参考 deepseek-harness 的 ``web_search`` / ``web_fetch`` 工具，但保持
CodeMate 的零新增运行时依赖：HTTP 使用标准库，输出和响应大小有硬上限，
并拒绝解析到本机/内网地址的 URL，避免把联网能力变成 SSRF 通道。
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import os
import re
import socket
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .base import Tool, ToolResult

DEFAULT_FETCH_TIMEOUT = 20
DEFAULT_SEARCH_TIMEOUT = 20
MAX_FETCH_BYTES = 2 * 1024 * 1024
MAX_FETCH_CHARS = 100_000
MAX_SEARCH_BYTES = 1 * 1024 * 1024
MAX_SEARCH_RESULTS = 8
MAX_REDIRECTS = 5
DEFAULT_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
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


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._field: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            href = attributes.get("href", "")
            parsed = urlparse(href)
            href = unquote(parse_qs(parsed.query).get("uddg", [href])[0])
            self._current = {"title": "", "url": href, "snippet": ""}
            self._field = "title"
        elif self._current is not None and "result__snippet" in classes:
            self._field = "snippet"

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._field:
            self._current[self._field] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current and self._field == "title":
            self._field = None
        elif self._current and self._field == "snippet" and tag in {"a", "div"}:
            self.results.append(self._current)
            self._current = None
            self._field = None


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
    description = "使用公共搜索引擎搜索当前网页信息，返回标题、URL 和摘要。"
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

    async def execute(
        self, query: str, limit: int = MAX_SEARCH_RESULTS
    ) -> ToolResult:
        if not query or not query.strip():
            return ToolResult.error("query 不能为空")
        limit = max(1, min(int(limit), MAX_SEARCH_RESULTS))
        endpoint = os.getenv("WEB_SEARCH_ENDPOINT", DEFAULT_SEARCH_ENDPOINT).strip()
        search_url = f"{endpoint}?q={quote_plus(query.strip())}"
        result = await asyncio.to_thread(
            _read_url, search_url, DEFAULT_SEARCH_TIMEOUT, MAX_SEARCH_BYTES
        )
        if "error" in result:
            return ToolResult.error(
                result["error"],
                suggestions=[
                    "确认网络可用，或设置 WEB_SEARCH_ENDPOINT 为可访问的搜索服务"
                ],
            )
        parser = _SearchParser()
        try:
            parser.feed(result["body"])
        except Exception:
            parser.results = []
        results = [item for item in parser.results if item.get("url")][:limit]
        if not results:
            return ToolResult.ok("没有找到搜索结果", query=query, total=0)
        lines = [f"搜索：{query.strip()}（{len(results)} 条）"]
        for index, item in enumerate(results, 1):
            title = re.sub(r"\s+", " ", html.unescape(item["title"])).strip()
            snippet = re.sub(r"\s+", " ", html.unescape(item["snippet"])).strip()
            lines.append(
                f"\n{index}. {title or item['url']}\nURL: {item['url']}\n摘要: {snippet or '无摘要'}"
            )
        return ToolResult.ok(
            "\n".join(lines),
            query=query,
            total=len(results),
            provider=endpoint,
        )
