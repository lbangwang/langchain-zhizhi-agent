"""职责：MCP 图片搜索 HTTP 服务，暴露 /search 与 /health。

技术点：BaseHTTPRequestHandler；DuckDuckGo + Unsplash 占位；默认 127.0.0.1:8765。
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse


def search_images(query: str, limit: int = 3) -> list[dict]:
    """功能：简易图片搜索，优先 DuckDuckGo Instant Answer 图标，不足用 Unsplash 占位。

    技术点：httpx 调 DuckDuckGo JSON；失败不抛，补 Unsplash Source URL。
    """
    q = (query or "").strip() or "landscape"
    items: list[dict] = []
    try:
        import httpx

        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": q, "format": "json", "pretty": 0},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            related = data.get("RelatedTopics") or []
            for topic in related:
                if len(items) >= limit:
                    break
                if isinstance(topic, dict) and topic.get("Icon", {}).get("URL"):
                    items.append(
                        {
                            "title": (topic.get("Text") or q)[:80],
                            "url": topic["Icon"]["URL"],
                        }
                    )
    except Exception:  # noqa: BLE001
        pass
    while len(items) < limit:
        i = len(items) + 1
        items.append(
            {
                "title": f"{q} #{i}",
                "url": f"https://source.unsplash.com/800x600/?{quote(q)}&sig={i}",
            }
        )
    return items[:limit]


class Handler(BaseHTTPRequestHandler):
    """职责：处理 /search、/health 的简易 HTTP Handler。

    技术点：query 中文 latin1→utf-8 还原；JSON 响应。
    """

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        """功能：把访问日志打到 stdout，带 mcp-image 前缀。

        技术点：覆盖默认 stderr 日志。
        """
        print(f"[mcp-image] {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        """功能：处理 GET /search 与 /health。

        技术点：utf-8 query 还原；404 其他路径。
        """
        # path 可能是 latin1 解码；中文 query 需按 utf-8 还原
        raw_path = self.path
        try:
            raw_path = raw_path.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        parsed = urlparse(raw_path)
        if parsed.path not in {"/search", "/health"}:
            self.send_response(404)
            self.end_headers()
            return
        if parsed.path == "/health":
            body = json.dumps({"ok": True, "service": "image-search-mcp"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        qs = parse_qs(parsed.query)
        q = unquote((qs.get("q") or ["nature"])[0])
        limit = int((qs.get("limit") or ["3"])[0])
        results = search_images(q, limit=limit)
        body = json.dumps(
            {"query": q, "results": results, "source": "mcp_servers.image_search"},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    """功能：启动图片搜索 HTTP 服务并阻塞监听。

    技术点：HTTPServer 127.0.0.1:8765。
    """
    host, port = "127.0.0.1", 8765
    server = HTTPServer((host, port), Handler)
    print(f"MCP image-search HTTP on http://{host}:{port}/search?q=cat")
    server.serve_forever()


if __name__ == "__main__":
    main()
