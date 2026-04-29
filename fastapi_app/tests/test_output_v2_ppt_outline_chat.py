from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi_app.services.output_v2_service import OutputV2Service


def _base_ppt_output() -> Dict[str, Any]:
    return {
        "id": "out_ppt_1",
        "target_type": "ppt",
        "title": "测试 PPT",
        "status": OutputV2Service.PPT_STAGE_OUTLINE,
        "pipeline_stage": OutputV2Service.PPT_STAGE_OUTLINE,
        "outline": [
            {
                "id": "slide_1",
                "pageNum": 1,
                "title": "原始标题",
                "layout_description": "原始布局",
                "key_points": ["原始要点"],
                "bullets": ["原始要点"],
            }
        ],
        "outline_global_directives": [],
        "source_paths": [],
        "source_names": [],
    }


def _service_with_manifest(
    tmp_path: Path,
    monkeypatch: Any,
    items: List[Dict[str, Any]],
) -> tuple[OutputV2Service, Path]:
    base_dir = tmp_path / "outputs"
    base_dir.mkdir(parents=True)
    (base_dir / "items.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    service = OutputV2Service()
    monkeypatch.setattr(service, "_base_dir", lambda *_args, **_kwargs: base_dir)
    return service, base_dir


def test_outline_chat_does_not_forward_notebook_conversation_history(tmp_path: Path, monkeypatch: Any) -> None:
    service, _ = _service_with_manifest(tmp_path, monkeypatch, [_base_ppt_output()])
    captured: Dict[str, Any] = {}

    async def fake_apply_outline_chat(**kwargs: Any) -> Dict[str, Any]:
        captured["conversation_history"] = kwargs.get("conversation_history")
        next_outline = [dict(kwargs["outline"][0], title="候选标题")]
        return {
            "outline": next_outline,
            "draft_global_directives": kwargs["global_directives"],
            "intent_summary": kwargs["intent_summary"],
        }

    monkeypatch.setattr(service, "_apply_outline_chat", fake_apply_outline_chat)

    asyncio.run(
        service.outline_chat(
            notebook_id="notebook_1",
            notebook_title="测试笔记本",
            user_id="user_1",
            email="user@example.com",
            output_id="out_ppt_1",
            message="把第一页标题改一下",
            active_slide_index=0,
            conversation_history=[{"role": "user", "content": "普通对话历史不应进入 PPT outline chat"}],
            api_url=None,
            api_key=None,
            model=None,
        )
    )

    assert captured["conversation_history"] is None


def test_discard_outline_chat_resets_pending_draft_without_changing_confirmed_outline(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    item = _base_ppt_output()
    confirmed_outline = item["outline"]
    draft_outline = [dict(confirmed_outline[0], title="候选标题")]
    item["outline_chat_sessions"] = [
        {
            "id": "session_1",
            "status": "active",
            "messages": [
                {
                    "id": "message_1",
                    "role": "assistant",
                    "content": "当前有一版候选大纲。",
                    "created_at": "2026-04-29T00:00:00+00:00",
                }
            ],
            "draft_outline": draft_outline,
            "draft_global_directives": [],
            "has_pending_changes": True,
            "created_at": "2026-04-29T00:00:00+00:00",
            "updated_at": "2026-04-29T00:00:00+00:00",
        }
    ]
    item["outline_chat_active_session_id"] = "session_1"
    item["outline_chat_draft_outline"] = draft_outline
    item["outline_chat_has_pending_changes"] = True
    service, _ = _service_with_manifest(tmp_path, monkeypatch, [item])
    normalized_confirmed_outline = service._normalize_ppt_outline(confirmed_outline)

    output, assistant_message = service.discard_outline_chat(
        notebook_id="notebook_1",
        notebook_title="测试笔记本",
        user_id="user_1",
        output_id="out_ppt_1",
    )

    assert output["outline"] == normalized_confirmed_outline
    assert output["outline_chat_has_pending_changes"] is False
    assert output["outline_chat_draft_outline"] == normalized_confirmed_outline
    active_session = output["outline_chat_sessions"][0]
    assert active_session["draft_outline"] == normalized_confirmed_outline
    assert active_session["has_pending_changes"] is False
    assert active_session["messages"][-1]["role"] == "system"
    assert "已放弃上一版候选大纲" in active_session["messages"][-1]["content"]
    assert assistant_message == "已放弃上一版候选大纲，继续基于当前正式大纲讨论。"
