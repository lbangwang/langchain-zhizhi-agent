"""职责：Skill 索引 + 按需加载正文（省 system prompt token）。

技术点：扫描 skills/*/SKILL.md；frontmatter 建索引；全文仅 load_skill_body 读取。
约定：system prompt 只注入索引；Agent 通过工具 load_skill(skill_id) 拉细则。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

# 简易 frontmatter：---\\nkey: value\\n---\\nbody
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class SkillIndex:
    """职责：Skill 轻量索引条目（只进 system prompt）。

    技术点：id/name/summary/triggers；path 供按需读正文。
    """

    id: str
    name: str
    summary: str
    triggers: tuple[str, ...]
    path: Path
    priority: int = 0


def _skills_root(root: str | None = None) -> Path:
    """功能：解析 skills 目录路径（相对则相对仓库根）。

    技术点：与历史 load_skill_texts 路径约定一致。
    """
    settings = get_settings()
    base = Path(root or settings.skills_dir)
    if not base.is_absolute():
        base = Path(__file__).resolve().parents[1] / base
    return base


def _parse_frontmatter_line_value(raw: str) -> str | list[str]:
    """功能：解析 frontmatter 单行值（标量或 [a, b] 列表）。

    技术点：不强制依赖 PyYAML，保持轻量。
    """
    v = raw.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
    return v.strip("'\"")


def _parse_skill_md(path: Path) -> tuple[dict[str, str | list[str] | int], str]:
    """功能：拆 SKILL.md 的 YAML-ish frontmatter 与正文。

    技术点：无 frontmatter 时 meta 为空、全文当 body（兼容旧包）。
    """
    raw = path.read_text(encoding="utf-8").strip()
    m = _FRONTMATTER.match(raw)
    if not m:
        return {}, raw
    meta_raw, body = m.group(1), m.group(2).strip()
    meta: dict[str, str | list[str] | int] = {}
    for line in meta_raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        parsed = _parse_frontmatter_line_value(val)
        if key == "priority":
            try:
                meta[key] = int(str(parsed))
            except ValueError:
                meta[key] = 0
        else:
            meta[key] = parsed
    return meta, body


def _summary_fallback(body: str, default: str) -> str:
    """功能：无 summary 时从正文取首条有用行作摘要。"""
    for ln in body.splitlines():
        s = ln.strip().lstrip("#").strip()
        if s and not s.startswith("---"):
            return s[:80]
    return default[:80]


@lru_cache(maxsize=8)
def build_skill_index(*, root: str | None = None) -> tuple[SkillIndex, ...]:
    """功能：扫描 skills/*/SKILL.md，构建进程级缓存的 Skill 索引。

    技术点：lru_cache 按 root 缓存；改文件后需重启或 clear_skill_index_cache()。
    """
    base = _skills_root(root)
    if not base.is_dir():
        return ()
    items: list[SkillIndex] = []
    for skill_md in sorted(base.glob("*/SKILL.md")):
        try:
            meta, body = _parse_skill_md(skill_md)
        except OSError:
            continue
        sid = str(meta.get("id") or skill_md.parent.name)
        name = str(meta.get("name") or sid)
        triggers_raw = meta.get("triggers") or []
        if isinstance(triggers_raw, str):
            triggers = tuple(x.strip() for x in triggers_raw.split(",") if x.strip())
        else:
            triggers = tuple(str(x) for x in triggers_raw)
        summary = str(meta.get("summary") or "").strip() or _summary_fallback(body, sid)
        priority = int(meta.get("priority") or 0)
        items.append(
            SkillIndex(
                id=sid,
                name=name,
                summary=summary,
                triggers=triggers,
                path=skill_md.resolve(),
                priority=priority,
            )
        )
    items.sort(key=lambda x: (-x.priority, x.id))
    return tuple(items)


def clear_skill_index_cache() -> None:
    """功能：清空索引缓存（热更新 Skill 文件后调用）。"""
    build_skill_index.cache_clear()


def load_skill_body(skill_id: str, *, root: str | None = None) -> str | None:
    """功能：按 skill_id 读取完整 Skill 正文（去掉 frontmatter）。

    技术点：只返回 body；未知 id 返回 None。
    """
    sid = (skill_id or "").strip()
    if not sid:
        return None
    idxs = build_skill_index(root=root) if root is not None else build_skill_index()
    for item in idxs:
        if item.id == sid:
            try:
                _meta, body = _parse_skill_md(item.path)
                return body.strip() or None
            except OSError:
                return None
    return None


def list_skill_ids(*, root: str | None = None) -> list[str]:
    """功能：返回已安装 skill_id 列表（供工具错误提示）。"""
    idxs = build_skill_index(root=root) if root is not None else build_skill_index()
    return [s.id for s in idxs]


def skills_index_block(*, max_skills: int | None = None) -> str:
    """功能：生成仅含目录索引的 system 段落（方案 B 常驻部分）。

    技术点：指导模型先选 id 再 load_skill；无 Skill 返回空串。
    """
    idxs = list(build_skill_index())
    if max_skills is not None:
        idxs = idxs[: max(0, int(max_skills))]
    if not idxs:
        return ""
    lines = [
        "",
        "# 已安装 Skill（目录索引）",
        "规则：",
        "1. 根据用户任务从下列 skill_id 中选择相关项；",
        "2. 需要流程细则时调用工具 load_skill(skill_id)；",
        "3. 禁止臆造未列出的 skill_id；未命中可不加载；",
        "4. 单轮最多 load_skill 2 次，已加载过的不要重复调用。",
        "",
    ]
    for s in idxs:
        trig = "、".join(s.triggers) if s.triggers else "（无）"
        lines.append(f"- `{s.id}` | {s.name} | 触发：{trig} | {s.summary}")
    lines.append("")
    return "\n".join(lines)


def skills_system_block() -> str:
    """功能：注入 Agent system prompt 的 Skill 段落（仅索引，不再拼全文）。

    技术点：方案 B；正文由 load_skill 工具按需加载。
    """
    return skills_index_block()


def load_skill_texts(*, root: str | None = None) -> list[str]:
    """功能：读取各 Skill 包全文（兼容旧测试/脚本；生产 prompt 勿再整包注入）。

    技术点：相对路径相对仓库根；读失败跳过该包。
    """
    base = _skills_root(root)
    if not base.is_dir():
        return []
    texts: list[str] = []
    for skill_md in sorted(base.glob("*/SKILL.md")):
        try:
            texts.append(skill_md.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return texts
