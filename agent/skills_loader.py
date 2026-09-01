"""职责：加载 skills/*/SKILL.md，注入 Agent system prompt。

技术点：按目录扫描 SKILL.md；拼进 create_agent 的 system_prompt。
"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def load_skill_texts(*, root: str | None = None) -> list[str]:
    """功能：读取各 Skill 包 SKILL.md 说明文本。

    技术点：相对路径相对仓库根；读失败跳过该包。
    """
    settings = get_settings()
    base = Path(root or settings.skills_dir)
    if not base.is_absolute():
        # 相对仓库根
        base = Path(__file__).resolve().parents[1] / base
    if not base.is_dir():
        return []
    texts: list[str] = []
    for skill_md in sorted(base.glob("*/SKILL.md")):
        try:
            texts.append(skill_md.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return texts


def skills_system_block() -> str:
    """功能：拼成可注入 Agent system prompt 的 Skill 段落。

    技术点：多份 SKILL.md 用 --- 拼接；无 Skill 返回空串。
    """
    parts = load_skill_texts()
    if not parts:
        return ""
    body = "\n\n---\n\n".join(parts)
    return (
        "\n\n# 已安装 Skill（按说明选择工具）\n"
        f"{body}\n"
    )
