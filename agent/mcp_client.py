"""职责：MCP 图片搜索客户端——优先 HTTP 调本地 MCP 服务，失败则本地占位。

技术点：httpx 调 mcp_servers.image_search；失败回退 Unsplash 占位 URL。
"""

from __future__ import annotations

import httpx

from app.config import get_settings


def search_images_via_mcp(query: str, *, limit: int = 3) -> str:
    """功能：调用图片搜索 MCP/HTTP 接口，返回可读文本。

    技术点：httpx GET；非 200 或异常时回退 _local_image_search。
    """
    settings = get_settings()
    url = settings.mcp_image_search_url
    try:
        resp = httpx.get(
            url,
            params={"q": query, "limit": limit},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("results") or data.get("images") or []
            if isinstance(items, list) and items:
                lines = []
                for i, it in enumerate(items[:limit], 1):
                    if isinstance(it, dict):
                        title = it.get("title") or it.get("alt") or f"image-{i}"
                        link = it.get("url") or it.get("link") or ""
                        lines.append(f"{i}. {title}\n   {link}")
                    else:
                        lines.append(f"{i}. {it}")
                return "图片搜索结果：\n" + "\n".join(lines)
            # 纯文本
            text = data.get("text") or resp.text
            return str(text)[:1500]
        # 非 200：尝试内置实现
    except Exception:  # noqa: BLE001
        pass
    return _local_image_search(query, limit=limit)


def _local_image_search(query: str, *, limit: int = 3) -> str:
    """功能：无 MCP 进程时用公开占位图服务生成可点击 URL。

    技术点：Unsplash Source 风格占位；不发起真实图库检索。
    """
    from urllib.parse import quote

    q = quote(query.strip() or "nature")
    # picsum + unsplash source 风格占位，便于演示
    results = []
    for i in range(1, limit + 1):
        results.append(
            f"{i}. {query} #{i}\n"
            f"   https://source.unsplash.com/800x600/?{q}&sig={i}"
        )
    return (
        "（MCP 服务未启动，使用本地占位图片链接）\n"
        + "\n".join(results)
        + "\n提示：可运行 `python -m mcp_servers.image_search` 启用真实 MCP HTTP。"
    )
