"""核心单测：不依赖外网 / 真实 LLM。

技术点：pytest + monkeypatch 假 LLM/Redis；测规划回退、HITL 名单、标题、配额、LangSmith 可关。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_multi_agent_plan_fallback(monkeypatch):
    """Planner 返回非 JSON 时回退启发式：调研 → 撰稿 → 交付。"""
    from agent import multi_agent

    monkeypatch.setattr(
        multi_agent,
        "chat_completion",
        lambda messages, model=None: "不是 json",
    )
    steps = multi_agent._plan_steps("写一份广州一日游攻略并导出 PDF")
    assert len(steps) == 3
    assert [s["action"] for s in steps] == ["research", "draft", "deliver"]


def test_multi_agent_plan_parses_json(monkeypatch):
    from agent import multi_agent

    monkeypatch.setattr(
        multi_agent,
        "chat_completion",
        lambda messages, model=None: (
            '[{"id":"1","title":"调研","action":"research"},'
            '{"id":"2","title":"写攻略","action":"draft"}]'
        ),
    )
    steps = multi_agent._plan_steps("广州攻略")
    assert steps[0]["action"] == "research"
    assert steps[1]["action"] == "draft"
    assert steps[-1]["action"] == "deliver"


def test_dangerous_tools_only_write_ops():
    from agent.hitl import DANGEROUS_TOOLS, is_dangerous

    assert "write_text_file" in DANGEROUS_TOOLS
    assert "create_pdf_report" in DANGEROUS_TOOLS
    assert "create_doc_report" in DANGEROUS_TOOLS
    assert "search_images" not in DANGEROUS_TOOLS
    assert "search_web" not in DANGEROUS_TOOLS
    assert is_dangerous("write_text_file")
    assert is_dangerous("create_doc_report")
    assert not is_dangerous("search_web")


def test_register_closed_when_disabled(monkeypatch):
    from app.errors import REGISTER_DISABLED
    from app.routers import auth

    class Fake:
        register_enabled = False

    monkeypatch.setattr(auth, "get_settings", lambda: Fake())
    closed = auth._register_closed()
    assert closed is not None
    assert closed.code == 403
    assert REGISTER_DISABLED.message in closed.message


def test_register_open_when_enabled(monkeypatch):
    from app.routers import auth

    class Fake:
        register_enabled = True

    monkeypatch.setattr(auth, "get_settings", lambda: Fake())
    assert auth._register_closed() is None


def test_seed_user_list():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_users.py"
    spec = importlib.util.spec_from_file_location("seed_users", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    names = [u[0] for u in mod.SEED_USERS]
    assert names == ["zhizhi", "lbwcc", "admin"]


def test_infer_export_format():
    from agent.tools import infer_export_format

    assert infer_export_format("写 intro.txt") == "txt"
    assert infer_export_format("导出一份 PDF 报告") == "pdf"
    assert infer_export_format("采用doc文档输出") == "docx"
    assert infer_export_format("生成 Word 攻略") == "docx"


def test_build_docx_and_pdf_bytes():
    from agent.tools import _build_docx_bytes, _build_pdf_bytes, _CJK_FONT_CANDIDATES

    assert _CJK_FONT_CANDIDATES
    docx = _build_docx_bytes("广州攻略", "白天去沙面，晚上北京路。")
    assert docx[:2] == b"PK"  # zip/docx
    pdf = _build_pdf_bytes("Test", "hello")
    assert pdf[:4] == b"%PDF"

def test_memory_should_summarize_threshold(monkeypatch):
    from agent import memory
    from app.config import get_settings

    settings = get_settings()
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(settings.memory_summarize_trigger)]
    assert memory.should_summarize(msgs) is True
    assert memory.should_summarize(msgs[:2]) is False


def test_summarize_and_trim_keeps_recent(monkeypatch):
    from agent import memory

    def fake_chat(messages):
        return "摘要：用户在讨论深圳自驾"

    monkeypatch.setattr(memory, "chat_completion", fake_chat)
    monkeypatch.setattr(
        memory,
        "get_settings",
        lambda: type(
            "S",
            (),
            {"memory_summarize_trigger": 4, "memory_keep_recent": 2},
        )(),
    )
    msgs = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
        {"role": "assistant", "content": "d"},
        {"role": "user", "content": "e"},
        {"role": "assistant", "content": "f"},
    ]
    out, summary = memory.summarize_and_trim(msgs)
    assert summary and "深圳" in summary
    assert any(m.get("content", "").startswith("【对话历史摘要】") for m in out)
    # 保留最近 2 条对话
    dialog = [m for m in out if m["role"] in {"user", "assistant"}]
    assert len(dialog) == 2
    assert dialog[-1]["content"] == "f"


def test_skills_loader_index_and_ondemand_body():
    """方案 B：system 只有索引；正文经 load_skill_body 按需读取。"""
    from agent.skills_loader import (
        build_skill_index,
        clear_skill_index_cache,
        load_skill_body,
        load_skill_texts,
        skills_system_block,
    )

    clear_skill_index_cache()
    texts = load_skill_texts()
    assert len(texts) >= 2

    idxs = build_skill_index()
    assert len(idxs) >= 2
    ids = {s.id for s in idxs}
    assert "web-research" in ids
    assert "report-writer" in ids

    block = skills_system_block()
    assert "目录索引" in block or "load_skill" in block
    assert "web-research" in block
    # 索引不应灌入大段流程细则（省 token）
    assert "流程建议" not in block

    body = load_skill_body("report-writer")
    assert body is not None
    assert "create_pdf_report" in body or "write_text_file" in body
    assert load_skill_body("not-exist-skill-xyz") is None


def test_basic_eval_cases_count():
    path = Path(__file__).resolve().parents[1] / "evals" / "cases_basic.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) == 20
    assert all("id" in c and "prompt" in c for c in cases)


def test_stop_key_helpers(monkeypatch):
    """停止信号 key 约定；无 Redis 时跳过写读。"""
    from app import stop_signal

    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, k, v, ex=None):
            store[k] = v

        def get(self, k):
            return store.get(k)

        def delete(self, k):
            store.pop(k, None)

    monkeypatch.setattr(stop_signal, "get_redis", lambda: FakeRedis())
    stop_signal.clear_stop("chat1")
    assert stop_signal.is_stopped("chat1") is False
    stop_signal.request_stop("chat1")
    assert stop_signal.is_stopped("chat1") is True
    stop_signal.clear_stop("chat1")
    assert stop_signal.is_stopped("chat1") is False


def test_health_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "langsmith_enabled" in data
    assert isinstance(data["langsmith_enabled"], bool)


def test_langsmith_off_when_flag_false(monkeypatch):
    """可关：开关 false 时不 wrap、不上报。"""
    from app import langsmith_setup

    fake = type(
        "S",
        (),
        {
            "langsmith_tracing": False,
            "langsmith_api_key": "lsv2_pt_dummy",
            "langsmith_project": "unit-test",
            "langsmith_endpoint": "https://api.smith.langchain.com",
            "langsmith_hide_io": False,
            "langsmith_max_input_chars": 4000,
        },
    )()
    monkeypatch.setattr(langsmith_setup, "get_settings", lambda: fake)
    langsmith_setup.reset_langsmith_state()
    st = langsmith_setup.configure_langsmith(force=True)
    assert st["enabled"] is False
    assert st["reason"] == "flag_off"
    sentinel = object()
    assert langsmith_setup.maybe_wrap_openai(sentinel) is sentinel
    from app.config import get_settings as real_gs

    monkeypatch.setattr(langsmith_setup, "get_settings", real_gs)
    langsmith_setup.reset_langsmith_state()
    langsmith_setup.configure_langsmith(force=True)


def test_langsmith_off_when_key_missing(monkeypatch):
    """开关 true 但没 Key：保持关闭，避免空 Key 打到云上报错。"""
    from app import langsmith_setup

    fake = type(
        "S",
        (),
        {
            "langsmith_tracing": True,
            "langsmith_api_key": "",
            "langsmith_project": "unit-test",
            "langsmith_endpoint": "https://api.smith.langchain.com",
            "langsmith_hide_io": False,
            "langsmith_max_input_chars": 4000,
        },
    )()
    monkeypatch.setattr(langsmith_setup, "get_settings", lambda: fake)
    langsmith_setup.reset_langsmith_state()
    st = langsmith_setup.configure_langsmith(force=True)
    assert st["enabled"] is False
    assert st["reason"] == "missing_api_key"
    from app.config import get_settings as real_gs

    monkeypatch.setattr(langsmith_setup, "get_settings", real_gs)
    langsmith_setup.reset_langsmith_state()
    langsmith_setup.configure_langsmith(force=True)


def test_langsmith_truncate_and_traced_noop(monkeypatch):
    from app import langsmith_setup

    long = "a" * 80
    out = langsmith_setup.truncate_for_smith(long, limit=20)
    assert out.startswith("a" * 20)
    assert "+60 chars" in out

    fake = type(
        "S",
        (),
        {
            "langsmith_tracing": False,
            "langsmith_api_key": "",
            "langsmith_project": "unit-test",
            "langsmith_endpoint": "https://api.smith.langchain.com",
            "langsmith_hide_io": False,
            "langsmith_max_input_chars": 4000,
        },
    )()
    monkeypatch.setattr(langsmith_setup, "get_settings", lambda: fake)
    langsmith_setup.reset_langsmith_state()
    langsmith_setup.configure_langsmith(force=True)

    @langsmith_setup.traced("unit.fn")
    def add(x, y):
        return x + y

    assert add(1, 2) == 3
    with langsmith_setup.langsmith_trace(name="unit.span"):
        pass

    # 回归：跨 copy_context 关闭不得抛 Token/Context 错误
    from contextvars import copy_context

    span = langsmith_setup.start_span(name="unit.cross-ctx")
    langsmith_setup._set_run_id("fake-run")
    copied = copy_context()
    copied.run(span.close)
    copied.run(lambda: langsmith_setup._set_run_id(None))
    from app.config import get_settings as real_gs

    monkeypatch.setattr(langsmith_setup, "get_settings", real_gs)
    langsmith_setup.reset_langsmith_state()
    langsmith_setup.configure_langsmith(force=True)


def test_app_error_codes():
    from app.errors import AGENT_TIMEOUT, QUOTA_EXCEEDED

    d = AGENT_TIMEOUT.to_dict()
    assert d["code"] == "AGENT_TIMEOUT"
    assert d["type"] == "error"
    assert QUOTA_EXCEEDED.code == "QUOTA_EXCEEDED"


def test_quota_without_redis(monkeypatch):
    from app import quota

    monkeypatch.setattr(quota, "_redis", lambda: None)
    ok, st = quota.check_and_consume_quota("u1")
    assert ok is True
    assert st["enforced"] is False


def test_conversation_title_uses_first_question():
    from app.utils import conversation_title, is_placeholder_title, public_reply_text

    assert is_placeholder_title("多 Agent")
    assert conversation_title("MULTI_AGENT", "帮忙出一份广州旅游攻略，采用doc输出") == (
        "【多Agent】帮忙出一份广州旅游攻略，采用doc输出"
        if len("帮忙出一份广州旅游攻略，采用doc输出") <= 28
        else conversation_title("MULTI_AGENT", "帮忙出一份广州旅游攻略，采用doc输出")
    )
    titled = conversation_title("MULTI_AGENT", "写一份广州一日游攻略")
    assert titled.startswith("【多Agent】")
    assert "写一份广州一日游攻略" in titled
    noisy = (
        "已生成 【多_Agent】【多_Agent】攻略.docx，"
        "artifact_id=52e79129616f43f49e03db9aab1f9dc3，"
        "下载 /api/artifacts/52e79129616f43f49e03db9aab1f9dc3/download"
        "（Word 文档 .docx，可用 Word/WPS 打开）"
    )
    clean = public_reply_text(noisy)
    assert "artifact_id" not in clean
    assert "/api/artifacts" not in clean
    assert "download" not in clean.lower() or "产物" in clean
    from agent.tools import _safe_filename

    fn = _safe_filename("【多Agent】【多 Agent】帮忙出一份旅行广州的旅游攻略（100字左右）", "docx")
    assert fn.endswith(".docx")
    assert "多_Agent" not in fn
    assert "多Agent" not in fn


def test_llm_usage_bag_accumulates():
    """用量袋按 Trace 累加；OpenAI / LangChain 字段名都能解析。"""
    from app.usage import bind_usage, parse_usage, pop_usage, record_usage_raw

    assert parse_usage({"prompt_tokens": 10, "completion_tokens": 5}) == (10, 5, 15)
    assert parse_usage({"input_tokens": 3, "output_tokens": 2}) == (3, 2, 5)
    bind_usage("trace-usage-test")
    record_usage_raw({"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14})
    record_usage_raw({"input_tokens": 1, "output_tokens": 1})
    meta = pop_usage("trace-usage-test")
    assert meta["prompt_tokens"] == 11
    assert meta["completion_tokens"] == 5
    assert meta["total_tokens"] == 16
    assert pop_usage("trace-usage-test") == {}
