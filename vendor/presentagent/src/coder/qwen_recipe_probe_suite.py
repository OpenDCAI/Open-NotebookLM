"""Lightweight probe suite for qwen_lib recipe diversity and safety."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .qwen_recipe_harness import run_recipe_harness


def build_probe_deck() -> dict[str, Any]:
    """Return fixed slide IRs that exercise non-two-column recipe choices."""

    theme = {
        "background_color": "#F7F4EE",
        "primary_color": "#134E8E",
        "accent_color": "#FFB33F",
        "text_color": "#1F2937",
        "font_family": "Aptos",
    }
    return {
        "title": "Qwen Recipe Probe Suite",
        "theme": theme,
        "slides": [
            _slide(
                "probe_quote_focus",
                "自我关怀是一项应得权利",
                "用一句核心判断建立全页观点。",
                "quote_focus",
                blocks=[{"kind": "quote", "content": "自我关怀不是额外享受，而是应得权利。"}],
                points=["从奢侈享受转向基本权利", "文化普及降低心理门槛", "常态机制支撑长期实践"],
            ),
            _slide(
                "probe_process_flow",
                "认知升级的三段路径",
                "展示从工具可及到范式转变的路径。",
                "process_flow",
                blocks=[{"kind": "bullet_list", "items": ["冥想/正念工具提升可及性", "打破优绩枷锁完成认知重构", "常态化机制带来范式转变"]}],
                points=["可及性: 工具进入日常", "重构: 打破优绩枷锁", "机制: 建立常态化实践", "结果: 应得权利"],
            ),
            _slide(
                "probe_comparison",
                "旧叙事与新叙事对照",
                "比较额外享受和应得权利两种框架。",
                "comparison",
                blocks=[{"kind": "bullet_list", "items": ["旧叙事: 自我关怀是奖励", "新叙事: 自我关怀是权利", "转变关键: 文化普及和机制支持"]}],
                points=["Before: 额外享受", "Bridge: 文化普及", "After: 应得权利", "Risk: 优绩主义压力"],
            ),
            _slide(
                "probe_metric_focus",
                "疗愈实践的三个衡量维度",
                "用指标化方式表达策略优先级。",
                "metric_focus",
                blocks=[{"kind": "metric_strip", "items": ["可及性: 72", "信任感: 64", "行动意愿: 51"]}],
                points=["可及性: 72", "信任感: 64", "行动意愿: 51"],
            ),
            _slide(
                "probe_framework_grid",
                "疗愈文化的 2x2 框架",
                "用框架组织工具、认知、机制和结果。",
                "title_body",
                blocks=[{"kind": "summary", "content": "疗愈文化需要同时覆盖工具、认知、机制和结果四个维度。"}],
                points=["工具: 冥想/正念", "认知: 打破优绩枷锁", "机制: 常态化支持", "结果: 应得权利"],
            ),
            _slide(
                "probe_cycle_loop",
                "常态化机制的闭环",
                "展示疗愈文化如何通过循环形成稳定实践。",
                "process_flow",
                blocks=[{"kind": "bullet_list", "items": ["触达", "尝试", "反馈", "固化"]}],
                points=["触达: 工具和内容进入日常", "尝试: 低门槛体验", "反馈: 形成正向感受", "固化: 机制化支持"],
            ),
            _slide(
                "probe_dense_text",
                "疗愈文化普及的执行要点",
                "密集要点需要自动分栏而不是挤成单列。",
                "title_body",
                blocks=[{"kind": "bullet_list", "items": ["降低入口门槛", "提供正念工具", "建立社区支持", "减少羞耻感", "强调长期机制", "保留个人节奏"]}],
                points=["降低入口门槛", "提供正念工具", "建立社区支持", "减少羞耻感", "强调长期机制", "保留个人节奏"],
            ),
            _slide(
                "probe_pyramid",
                "疗愈支持的层级优先级",
                "用层级结构表达从基础触达到高阶机制的优先顺序。",
                "metric_focus",
                blocks=[{"kind": "summary", "content": "疗愈支持应先解决可及性，再进入信任、行动和机制化。"}],
                points=["基础层: 工具可及", "中间层: 信任和低门槛体验", "高阶层: 行动意愿", "顶层: 常态化机制"],
            ),
            _slide(
                "probe_funnel",
                "从触达到稳定实践的转化漏斗",
                "展示用户如何从接触内容逐步转化为长期实践。",
                "process_flow",
                blocks=[{"kind": "bullet_list", "items": ["触达内容", "低门槛尝试", "形成正反馈", "纳入日常机制"]}],
                points=["触达: 看到正念/冥想入口", "尝试: 完成一次低成本体验", "反馈: 感到压力下降", "稳定: 进入长期实践"],
            ),
            _slide(
                "probe_evidence_cards",
                "认知升级的证据支撑",
                "把关键判断和支撑依据并列呈现，避免空泛结论。",
                "title_body",
                blocks=[
                    {
                        "kind": "bullet_list",
                        "items": [
                            "判断: 自我关怀从奖励转为权利",
                            "依据: 工具普及降低实践门槛",
                            "依据: 文化讨论减少羞耻感",
                            "依据: 常态机制支撑长期行动",
                        ],
                    }
                ],
                points=["Claim: 权利化叙事增强正当性", "Evidence: 工具普及", "Evidence: 羞耻感下降", "Evidence: 机制化支持"],
            ),
            _slide(
                "probe_visual_compare",
                "认知升级前后状态",
                "用视觉对照表达转变前后的心理模型。",
                "visual_focus",
                blocks=[{"kind": "summary", "content": "从额外享受到应得权利，是一次心理模型的切换。"}],
                points=["升级前: 奖励式自我关怀", "升级后: 权利式自我关怀"],
                visuals=[
                    {"slot_id": "left_visual", "caption": "升级前", "intent": "展示额外享受式的自我关怀"},
                    {"slot_id": "right_visual", "caption": "升级后", "intent": "展示应得权利式的自我关怀"},
                ],
            ),
        ],
    }


def run_probe_suite(
    client,
    output_dir: str | Path,
    *,
    render: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    deck = build_probe_deck()
    slides = deck["slides"][: max(0, int(limit))] if limit is not None else deck["slides"]
    (output / "probe_deck.json").write_text(
        json.dumps({**deck, "slides": slides}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    results = []
    for index, slide_ir in enumerate(slides, start=1):
        slide_id = str(slide_ir.get("slide_id") or f"probe_{index:02d}")
        result = run_recipe_harness(client, {**deck, "slides": slides}, slide_ir, {}, str(output / slide_id), render=render)
        results.append(result)

    summary = summarize_probe_results(results)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def summarize_probe_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    layout_counts: Counter[str] = Counter()
    element_variant_counts: Counter[str] = Counter()
    composition_variant_counts: Counter[str] = Counter()
    audit_status_counts: Counter[str] = Counter()
    failed_slides = []

    for result in results:
        recipe = result.get("recipe", {}) if isinstance(result, dict) else {}
        layout_counts[str(recipe.get("layout", {}).get("kind") or "unknown")] += 1
        for item in recipe.get("elements", []) or []:
            element_variant_counts[str(item.get("variant") or "unknown")] += 1
        for item in recipe.get("compositions", []) or []:
            composition_variant_counts[str(item.get("variant") or "unknown")] += 1
        audit = result.get("render_audit", {}) if isinstance(result, dict) else {}
        status = str(audit.get("status") or ("not_rendered" if not audit else "unknown"))
        audit_status_counts[status] += 1
        if status == "fail":
            failed_slides.append(str(result.get("slide_id") or "unknown"))

    total = len(results)
    two_column_count = layout_counts.get("two_column", 0)
    red_flags = []
    if total and two_column_count / total > 0.7:
        red_flags.append("layout_diversity_low_two_column_dominant")
    if len(composition_variant_counts) <= 2 and total >= 4:
        red_flags.append("composition_diversity_low")
    if failed_slides:
        red_flags.append("render_audit_failures")

    return {
        "total_slides": total,
        "layout_counts": dict(layout_counts),
        "element_variant_counts": dict(element_variant_counts),
        "composition_variant_counts": dict(composition_variant_counts),
        "audit_status_counts": dict(audit_status_counts),
        "two_column_ratio": round(two_column_count / total, 3) if total else 0.0,
        "failed_slides": failed_slides,
        "red_flags": red_flags,
    }


def _slide(
    slide_id: str,
    title: str,
    core_message: str,
    layout_name: str,
    *,
    blocks: list[dict[str, Any]],
    points: list[str],
    visuals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "slide_id": slide_id,
        "type": "content",
        "section_id": "probe_section",
        "title": title,
        "subtitle": "",
        "core_message": core_message,
        "layout": {"name": layout_name, "density": "balanced"},
        "blocks": [
            {
                "block_id": f"{slide_id}_block_{index + 1}",
                "kind": block.get("kind", "summary"),
                "content": block.get("content", ""),
                "items": block.get("items", []),
            }
            for index, block in enumerate(blocks)
        ],
        "points": [{"point_id": f"{slide_id}_point_{index + 1}", "text": text} for index, text in enumerate(points)],
        "visuals": visuals or [],
    }
