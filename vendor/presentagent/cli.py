#!/usr/bin/env python3
"""PresentAgent CLI entrypoint."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sys
from pathlib import Path

from src.coder.pptx_coder import PPTXCoder
from src.llm.client import LLMClient
from src.materials.material_collector import MaterialCollector
from src.materials.material_resolver import MaterialResolver
from src.materials.image_generator import ImageGenerator
from src.materials.vlm_descriptor import VLMDescriptor
from src.planner.ir_artifacts import IRArtifactWriter
from src.planner.longdoc_planner import LongDocPlanner
from src.parsers.mineru_parser import MinerUParser
from src.planner.slide_planner import SlidePlanner
from src.refiner.react_refiner import ReactRefiner
from src.utils.config import Config
from src.utils.token_tracker import get_global_tracker, reset_global_tracker


AUTO_SPLIT_TARGET_THRESHOLD = 9
QwenRecipeCoder = None
QwenRecipeRefiner = None


class PipelineProgress:
    def __init__(self, stages: list[tuple[str, str]]) -> None:
        self.stage_index = {stage_id: index for index, (stage_id, _) in enumerate(stages)}
        self.stage_labels = {stage_id: label for stage_id, label in stages}
        self.total_stages = len(stages)
        self.current_stage_id = stages[0][0] if stages else ""
        self.current_current = 0
        self.current_total = 1
        self.current_detail = ""
        self.is_tty = sys.stdout.isatty()

    def start(self, stage_id: str, detail: str = "") -> None:
        self.current_stage_id = stage_id
        self.current_current = 0
        self.current_total = 1
        self.current_detail = detail
        self._render()

    def update(self, stage_id: str, current: int, total: int, detail: str = "") -> None:
        self.current_stage_id = stage_id
        self.current_current = max(0, current)
        self.current_total = max(1, total)
        self.current_detail = detail
        self._render()

    def complete(self, stage_id: str, detail: str = "") -> None:
        self.current_stage_id = stage_id
        self.current_current = 1
        self.current_total = 1
        self.current_detail = detail or "done"
        self._render(final=True)

    def _render(self, final: bool = False) -> None:
        stage_position = self.stage_index.get(self.current_stage_id, 0) + 1
        stage_fraction = min(self.current_current / self.current_total, 1.0)
        overall_fraction = ((stage_position - 1) + stage_fraction) / max(self.total_stages, 1)
        bar_width = 24
        filled = int(bar_width * overall_fraction)
        bar = "#" * filled + "-" * (bar_width - filled)
        label = self.stage_labels.get(self.current_stage_id, self.current_stage_id)
        detail = f" | {self.current_detail}" if self.current_detail else ""
        line = (
            f"[{bar}] {overall_fraction * 100:5.1f}% "
            f"({stage_position}/{self.total_stages}) {label} "
            f"{self.current_current}/{self.current_total}{detail}"
        )
        if self.is_tty:
            end = "\n" if final else "\r"
            print(line.ljust(140), end=end, flush=True)
        else:
            print(line, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI PPT生成CLI")
    parser.add_argument("pdf_path", help="输入PDF路径，支持本地文件或公开URL")
    parser.add_argument("--output", default="output.pptx", help="输出PPT路径")
    parser.add_argument("--code-output", default="", help="可选：保存生成的Python代码路径")
    parser.add_argument("--coder-mode", choices=["library", "direct"], default="library", help="step4 coder模式")
    parser.add_argument("--resume-output-dir", default="", help="复用已有输出目录，跳过可复用阶段并仅补缺产物")
    parser.add_argument("--parse-only", action="store_true", help="只执行 MinerU 解析")
    parser.add_argument("--materials-only", action="store_true", help="执行到 step 1 的 self 素材事实层与 slide_briefs 后停止")
    parser.add_argument("--no-react", action="store_true", help="跳过ReAct优化")
    parser.add_argument("--language", choices=["english", "chinese"], default="english", help="PPT语言模式：english 或 chinese")
    parser.add_argument("--complexity", choices=["simple", "balanced", "complex"], default="balanced", help="PPT复杂度：simple（简单）、balanced（均衡）或 complex（复杂）")
    parser.add_argument("--target-slides", type=int, default=0, help="目标页数，0 表示由 LLM 自由规划")
    parser.add_argument("--max-slides", type=int, default=0, help="临时限制最大页数，0 表示不限制")
    parser.add_argument("--model-profile", choices=["general", "qwen", "claude"], default=_default_model_profile(), help="模型画像：general 走通用路径，qwen/claude 启用各自专属兼容逻辑")
    parser.add_argument("--llm-backend", choices=["remote", "local"], default=_default_llm_backend(), help="Step 1/2/4/5 使用的 LLM 后端")
    parser.add_argument("--local-llm-api-base", default="", help="本地 LLM 接口地址，可选覆盖默认值")
    parser.add_argument("--local-llm-model", default="", help="本地 LLM 模型名，可选覆盖默认值")
    args = parser.parse_args()

    # Reset token tracker at the start
    reset_global_tracker()
    tracker = get_global_tracker()

    config = Config()
    # Override config with CLI arguments
    if args.language:
        config.language_mode = args.language
    if args.complexity:
        config.complexity_level = args.complexity
    if args.model_profile:
        config.model_profile = args.model_profile
    if args.max_slides > 0:
        config.max_slides = args.max_slides

    target_slide_count = args.target_slides if args.target_slides > 0 else None
    slide_limit = config.max_slides if config.max_slides > 0 else None
    planning_target_slide_count = _resolve_planning_target_slide_count(target_slide_count, slide_limit)
    slide_ir_strategy = _choose_slide_ir_strategy(target_slide_count)
    llm_api_base, llm_model = _resolve_llm_settings(
        backend=args.llm_backend,
        config=config,
        local_api_base_override=args.local_llm_api_base,
        local_model_override=args.local_llm_model,
    )
    run_react = not args.no_react
    stage_defs = [
        ("step1", "Step 1 Parse+Brief"),
        ("step2", "Step 2 IR"),
        ("step3", "Step 3 Materials"),
        ("step4", "Step 4 Coder"),
    ]
    if run_react:
        stage_defs.append(("step5", "Step 5 Refiner"))
    progress = PipelineProgress(stage_defs)

    resume_output_dir = args.resume_output_dir.strip()
    slide_briefs = None
    slide_briefs_path = ""
    resume_ir = None
    if resume_output_dir:
        parsed = _load_existing_parse(Path(resume_output_dir))
        progress.start("step1", "resume parse/materials/briefs")
        print("Step 1: 复用已有结果，补齐 self 素材与 slide_briefs...")
    else:
        print("Step 1: 解析 PDF，准备 self 素材并生成 slide_briefs...")
        tracker.start_step("step1_parse")
        progress.start("step1", "mineru parse")
        pdf_parser = MinerUParser(
            output_dir=config.output_dir,
            api_token=config.mineru_api_token,
            api_base=config.mineru_api_base,
            model_version=config.mineru_model_version,
            poll_interval=config.mineru_poll_interval,
            timeout=config.mineru_parse_timeout,
        )
        parsed = pdf_parser.parse(args.pdf_path)
    progress.update("step1", 1, 3, f"parse {len(parsed['images'])} images")

    print(f"  - Markdown: {parsed['markdown_path']}")
    print(f"  - 图片目录: {parsed['images_dir']}")
    print(f"  - 图片数量: {len(parsed['images'])}")

    if args.parse_only:
        print(f"✓ Step 1完成，产物已保存至: {parsed['output_dir']}")
        return

    llm = LLMClient(
        config.llm_api_key,
        llm_api_base,
        llm_model,
        client_type="llm",
        model_profile=config.model_profile,
    )
    vlm = LLMClient(config.vlm_api_key, config.vlm_api_base, config.vlm_model, client_type="vlm")
    artifact_writer = IRArtifactWriter()

    tracker.start_step("step1_materials")
    descriptor = VLMDescriptor(vlm, max_workers=config.vlm_max_workers)
    collector = MaterialCollector(descriptor)
    materials = None
    if resume_output_dir:
        try:
            materials = _load_existing_materials(Path(parsed["output_dir"]))
            progress.update("step1", 2, 3, f"resume {len(materials.get('assets', []))} assets")
        except FileNotFoundError:
            materials = None
    if materials is None:
        materials = collector.collect_with_context(
            parsed["output_dir"],
            markdown_text=parsed["markdown"],
            progress_callback=lambda current, total, detail: progress.update(
                "step1",
                current,
                max(total, 1) * 3,
                f"caption {current}/{total}: {detail}",
            ),
        )
        progress.update("step1", 2, 3, f"{len(materials['assets'])} assets")

    print(f"  - Markdown: {materials['markdown_path']}")
    print(f"  - 素材清单: {materials['manifest_path']}")
    print(f"  - 图片数量: {len(materials['images'])}")

    if args.materials_only:
        print(f"✓ self 素材事实层已保存至: {materials['materials_dir']}")
        return

    if resume_output_dir:
        try:
            existing_slide_briefs, existing_slide_briefs_path = _load_existing_slide_briefs(Path(parsed["output_dir"]))
            if _has_usable_slide_briefs(existing_slide_briefs):
                slide_briefs = existing_slide_briefs
                slide_briefs_path = existing_slide_briefs_path
            else:
                print("  - 检测到空的 slide_briefs checkpoint，将重新生成")
                slide_briefs = None
        except FileNotFoundError:
            slide_briefs = None
    else:
        slide_briefs = None
    if slide_briefs is None:
        tracker.start_step("step1_briefs")
        longdoc_planner = LongDocPlanner(
            llm,
            chunk_char_limit=config.longdoc_chunk_char_limit,
            overlap_chars=config.longdoc_overlap_chars,
            max_workers=config.planner_max_workers,
            language_mode=config.language_mode,
            complexity_level=config.complexity_level,
        )
        slide_briefs = longdoc_planner.build_slide_briefs(
            materials["markdown"],
            target_slide_count=planning_target_slide_count,
            progress_callback=lambda current, total, detail: progress.update("step1", 2 + current, 2 + total, detail),
        )
        slide_briefs_path = artifact_writer.write_slide_briefs(
            slide_briefs,
            parsed["output_dir"],
            stage="planned",
        )
    slide_briefs = _limit_slide_briefs(slide_briefs, slide_limit)
    progress.complete(
        "step1",
        f"{slide_briefs['longdoc_profile']['chunk_count']} chunks, {len(slide_briefs.get('slide_briefs', []))} briefs",
    )
    print(f"  - 目标页数预算: {slide_briefs['longdoc_profile']['target_slide_count']}")
    print(f"  - Chunk数量: {slide_briefs['longdoc_profile']['chunk_count']}")
    print(f"  - Slide briefs数量: {len(slide_briefs.get('slide_briefs', []))}")
    if slide_limit is not None:
        print(f"  - 临时页数上限: {slide_limit}")
    print(f"  - Slide briefs: {slide_briefs_path}")

    resolver = MaterialResolver(
        descriptor=descriptor,
        image_generator=ImageGenerator(
            config.image_api_key,
            config.image_api_base,
            model=config.image_generation_model,
        ),
        collector=collector,
    )

    print("Step 2: 基于 slide_briefs 生成 Deck IR + Slide IR...")
    tracker.start_step("step2_ir")
    existing_deck_stage = None
    if resume_output_dir:
        resume_ir = _load_existing_ir(Path(parsed["output_dir"]), stage="planned")
        if resume_ir is None:
            existing_deck_stage = _load_existing_deck_stage(Path(parsed["output_dir"]))
    if resume_ir is not None:
        ir = _limit_ir_slides(resume_ir, slide_limit)
        progress.start("step2", "reuse planned ir")
        progress.complete("step2", f"{len(ir.get('slides', []))} slides reused")
        print(f"  - 复用已有 deck IR: {Path(parsed['output_dir']) / 'ir' / 'planned' / 'final_ir.json'}")
        print(f"  - Deck标题: {ir['title']}")
        print(f"  - 页数: {len(ir.get('slides', []))}")
        print(f"  - 素材请求数: {len(ir.get('material_requests', []))}")
    else:
        planner = SlidePlanner(
            llm,
            max_workers=config.planner_max_workers,
            language_mode=config.language_mode,
            complexity_level=config.complexity_level,
            slide_ir_strategy=slide_ir_strategy,
            target_slide_count=planning_target_slide_count,
            auto_split_threshold=AUTO_SPLIT_TARGET_THRESHOLD,
        )
        progress.start("step2", "slide ir planning")
        existing_planned_slides = artifact_writer.load_existing_slide_docs(parsed["output_dir"], stage="planned")
        ir = planner.plan_deck(
            materials["markdown"],
            materials,
            slide_briefs=slide_briefs,
            progress_callback=lambda current, total, detail: progress.update("step2", current, total, detail),
            deck_stage_callback=lambda deck_stage: artifact_writer.write_deck_stage(
                deck_stage,
                parsed["output_dir"],
                stage="planned",
            ),
            slide_callback=lambda slide, requests, index, _total: artifact_writer.write_single_slide(
                {
                    "metadata": {"deck_id": slide.get("deck_id", ""), "schema_name": "presentagent.deck_ir"},
                    "title": slide_briefs.get("title_hint", ""),
                    "subtitle": slide_briefs.get("subtitle_hint", ""),
                    "theme": {},
                    "storyline": slide_briefs.get("storyline_hint", {}),
                    "planner_notes": slide_briefs.get("planner_notes", []),
                },
                slide,
                parsed["output_dir"],
                stage="planned",
                slide_number=index,
                material_requests=requests,
            ),
            existing_slides=existing_planned_slides,
            existing_deck_stage=existing_deck_stage,
        )
        ir = _limit_ir_slides(ir, slide_limit)
        progress.complete("step2", f"{len(ir.get('slides', []))} slides")
        print(f"  - Deck标题: {ir['title']}")
        print(f"  - 页数: {len(ir.get('slides', []))}")
        print(f"  - 素材请求数: {len(ir.get('material_requests', []))}")
        planned_artifacts = artifact_writer.write(
            ir,
            parsed["output_dir"],
            stage="planned",
            slide_briefs=slide_briefs,
        )
        print(f"  - 已导出 deck IR: {planned_artifacts['deck_path']}")
        print(f"  - 已导出 slide IR 目录: {planned_artifacts['slides_dir']}")
        if planned_artifacts.get("slide_briefs_path"):
            print(f"  - 已导出 slide_briefs: {planned_artifacts['slide_briefs_path']}")

    print("Step 3: 执行素材请求并回填 IR...")
    tracker.start_step("step3_materials")
    progress.start("step3", "resolve material requests")
    if resume_output_dir:
        final_ir_path = Path(parsed["output_dir"]) / "ir" / "final" / "final_ir.json"
        if final_ir_path.exists():
            import json
            ir = json.loads(final_ir_path.read_text(encoding="utf-8"))
            ir = _limit_ir_slides(ir, slide_limit)
            progress.complete("step3", "reused final ir")
            print(f"  - 复用已解析IR: {final_ir_path}")
            print(f"  - 已解析素材请求: {len(ir.get('material_requests', []))}")
        else:
            resolved = resolver.resolve(
                materials,
                ir,
                progress_callback=lambda current, total, detail: progress.update("step3", current, total, detail),
            )
            materials = resolved["materials"]
            ir = _limit_ir_slides(resolved["ir"], slide_limit)
            if not ir.get("material_requests"):
                progress.update("step3", 1, 1, "no material requests")
            progress.complete("step3", f"{len(resolved['resolved_requests'])} requests")
            print(f"  - 已解析素材请求: {len(resolved['resolved_requests'])}")
            if resolved.get("resolution_path"):
                print(f"  - 回填结果: {resolved['resolution_path']}")
            final_artifacts = artifact_writer.write(ir, parsed["output_dir"], stage="final", slide_briefs=slide_briefs)
            print(f"  - 最终 deck IR: {final_artifacts['deck_path']}")
    else:
        resolved = resolver.resolve(
            materials,
            ir,
            progress_callback=lambda current, total, detail: progress.update("step3", current, total, detail),
        )
        materials = resolved["materials"]
        ir = _limit_ir_slides(resolved["ir"], slide_limit)
        if not ir.get("material_requests"):
            progress.update("step3", 1, 1, "no material requests")
        progress.complete("step3", f"{len(resolved['resolved_requests'])} requests")
        print(f"  - 已解析素材请求: {len(resolved['resolved_requests'])}")
        if resolved.get("resolution_path"):
            print(f"  - 回填结果: {resolved['resolution_path']}")
        final_artifacts = artifact_writer.write(ir, parsed["output_dir"], stage="final", slide_briefs=slide_briefs)
        print(f"  - 最终 deck IR: {final_artifacts['deck_path']}")

    print("Step 4: 生成PPT...")
    tracker.start_step("step4_codegen")
    progress.start("step4", "generate and render pptx")
    coder = _build_step4_coder(
        args.coder_mode,
        llm,
        config,
    )
    code_artifact_dir = str(Path(parsed["output_dir"]) / "code" / "generated")
    initial_output = str(Path(parsed["output_dir"]) / "initial.pptx")

    if resume_output_dir and Path(initial_output).exists():
        progress.complete("step4", "reused initial.pptx")
        print(f"  - 复用初版PPTX: {initial_output}")
    else:
        coder.generate_and_render(
            ir,
            materials,
            initial_output,
            mode=args.coder_mode,
            save_code_path=None if not args.no_react else (args.code_output or None),
            artifact_dir=code_artifact_dir,
            progress_callback=lambda event, current, total, detail: progress.update(
                "step4",
                current if event == "codegen" else total,
                total,
                ("codegen" if event == "codegen" else "execute") + f" {detail}",
            ),
        )
        progress.complete("step4", initial_output)
        print(f"  - 初版PPTX: {initial_output}")

    if run_react:
        print("Step 5: ReAct优化...")
        tracker.start_step("step5_refine")
        progress.start("step5", "react refine")
        refiner = _build_step5_refiner(
            args.coder_mode,
            llm,
            vlm,
            coder,
            config,
        )

        if resume_output_dir:
            refined_ir_path = Path(parsed["output_dir"]) / "ir" / "refined" / "final_ir.json"
            refined_pptx_path = Path(parsed["output_dir"]) / "refined_final.pptx"
            if refined_ir_path.exists() and refined_pptx_path.exists():
                import json
                import shutil
                ir = json.loads(refined_ir_path.read_text(encoding="utf-8"))
                _copy_if_different(refined_pptx_path, args.output)
                progress.complete("step5", "reused refined ir and pptx")
                print(f"  - 复用已优化IR: {refined_ir_path}")
                print(f"  - 复用已优化PPTX: {refined_pptx_path}")
                print(f"  - ReAct已优化页数: {len(ir.get('slides', []))}")
            else:
                refined = refiner.refine_deck(
                    ir,
                    materials,
                    parsed["output_dir"],
                    mode=args.coder_mode,
                    progress_callback=lambda current, total, detail: progress.update("step5", current, total, detail),
                )
                ir = _limit_ir_slides(refined["ir"], slide_limit)
                refined_artifacts = artifact_writer.write(ir, parsed["output_dir"], stage="refined", slide_briefs=slide_briefs)
                final_pptx = refined.get("final_pptx")
                if final_pptx:
                    _copy_if_different(final_pptx, args.output)
                    print(f"  - 最终PPTX: {args.output}")
                print(f"  - ReAct已优化页数: {len(ir.get('slides', []))}")
                print(f"  - Refined deck IR: {refined_artifacts['deck_path']}")
                progress.complete("step5", f"{len(ir.get('slides', []))} slides refined")
        else:
            refined = refiner.refine_deck(
                ir,
                materials,
                parsed["output_dir"],
                mode=args.coder_mode,
                progress_callback=lambda current, total, detail: progress.update("step5", current, total, detail),
            )
            ir = _limit_ir_slides(refined["ir"], slide_limit)
            refined_artifacts = artifact_writer.write(ir, parsed["output_dir"], stage="refined", slide_briefs=slide_briefs)
            final_pptx = refined.get("final_pptx")
            if final_pptx:
                _copy_if_different(final_pptx, args.output)
            print(f"  - ReAct已优化页数: {len(ir.get('slides', []))}")
            print(f"  - Refined deck IR: {refined_artifacts['deck_path']}")
            print(f"  - 最终PPTX: {args.output}")
            progress.complete("step5", f"{len(ir.get('slides', []))} slides refined")

    if args.no_react:
        _copy_if_different(initial_output, args.output)
        print(f"  - 最终PPTX: {args.output}")

    print(f"✓ 完成！PPT已保存至: {args.output}")

    # Save token usage report
    output_dir = Path(parsed["output_dir"])
    token_json_path = output_dir / "token_usage.json"
    token_txt_path = output_dir / "token_usage.txt"

    tracker.save_to_file(token_json_path)
    tracker.save_to_txt(token_txt_path)

    print(f"\n📊 Token使用统计已保存:")
    print(f"  - JSON格式: {token_json_path}")
    print(f"  - 文本格式: {token_txt_path}")

    # Print summary
    summary = tracker.to_dict()["summary"]
    print(f"\n总计:")
    print(f"  - LLM Tokens: {summary['total_llm_tokens']:,}")
    print(f"  - VLM Tokens: {summary['total_vlm_tokens']:,}")
    print(f"  - 图片生成次数: {summary['total_image_generations']:,}")


def _default_llm_backend() -> str:
    value = os.getenv("PRESENT_AGENT_USE_LOCAL_LLM", "").strip().lower()
    return "local" if value in {"1", "true", "yes", "on"} else "remote"


def _default_model_profile() -> str:
    value = os.getenv("PRESENT_AGENT_MODEL_PROFILE", "").strip().lower()
    return "qwen" if value == "qwen" else "general"


def _resolve_planning_target_slide_count(
    target_slide_count: int | None,
    slide_limit: int | None,
) -> int | None:
    if target_slide_count is not None and target_slide_count > 0:
        return target_slide_count
    if slide_limit is not None and slide_limit > 0:
        return slide_limit
    return None


def _choose_slide_ir_strategy(target_slide_count: int | None) -> str:
    if target_slide_count is None or target_slide_count <= 0:
        return "auto"
    return "single" if target_slide_count <= AUTO_SPLIT_TARGET_THRESHOLD else "split"


def _resolve_llm_settings(
    *,
    backend: str,
    config: Config,
    local_api_base_override: str = "",
    local_model_override: str = "",
) -> tuple[str, str]:
    if backend == "local":
        return (
            local_api_base_override.strip() or config.local_llm_api_base,
            local_model_override.strip() or config.local_llm_model,
        )
    return config.llm_api_base, config.llm_model


def _build_step4_coder(
    coder_mode: str,
    llm,
    config: Config,
):
    if config.model_profile == "qwen" and coder_mode == "library":
        coder_cls = _get_qwen_recipe_coder_class()
        return coder_cls(
            llm,
            max_workers=config.coder_max_workers,
            max_attempts=1,
            complexity_level=config.complexity_level,
        )
    return PPTXCoder(
        llm,
        max_workers=config.coder_max_workers,
        max_attempts=3,
    )


def _get_qwen_recipe_coder_class():
    global QwenRecipeCoder
    if QwenRecipeCoder is None:
        from src.coder.qwen_recipe_coder import QwenRecipeCoder as LoadedQwenRecipeCoder

        QwenRecipeCoder = LoadedQwenRecipeCoder
    return QwenRecipeCoder


def _build_step5_refiner(
    coder_mode: str,
    llm,
    vlm,
    coder,
    config: Config,
):
    if config.model_profile == "qwen" and coder_mode == "library":
        refiner_cls = _get_qwen_recipe_refiner_class()
        return refiner_cls(llm, vlm_client=vlm, max_iterations=2, threshold=8.0)
    return ReactRefiner(
        llm_client=llm,
        vlm_client=vlm,
        coder=coder,
        max_iterations=3,
        threshold=8.0,
        max_workers=1,
    )


def _get_qwen_recipe_refiner_class():
    global QwenRecipeRefiner
    if QwenRecipeRefiner is None:
        from src.refiner.qwen_recipe_refiner import QwenRecipeRefiner as LoadedQwenRecipeRefiner

        QwenRecipeRefiner = LoadedQwenRecipeRefiner
    return QwenRecipeRefiner


def _copy_if_different(src: str | Path, dst: str | Path) -> None:
    src_path = Path(src)
    dst_path = Path(dst)
    if src_path.resolve() == dst_path.resolve():
        return
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dst_path)


def _load_existing_parse(document_dir: Path) -> dict[str, object]:
    markdown_path = document_dir / "markdown" / "full.md"
    if not markdown_path.exists():
        raise FileNotFoundError(f"Missing markdown at {markdown_path}")
    images_dir = document_dir / "images" / "self"
    images = [str(path) for path in sorted(images_dir.glob("*")) if path.is_file()]
    raw_output_dir = document_dir / "_mineru_raw"
    return {
        "markdown": markdown_path.read_text(encoding="utf-8"),
        "markdown_path": str(markdown_path),
        "images": images,
        "images_dir": str(images_dir),
        "output_dir": str(document_dir),
        "raw_output_dir": str(raw_output_dir),
    }


def _load_existing_materials(document_dir: Path) -> dict[str, object]:
    materials_dir = document_dir / "materials"
    manifest_path = materials_dir / "material_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing material manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptions_path = materials_dir / "asset_descriptions.json"
    asset_catalog_path = materials_dir / "asset_catalog.json"
    request_contexts_path = materials_dir / "asset_request_contexts.json"
    markdown_path = Path(manifest.get("markdown_path") or (document_dir / "markdown" / "full.md"))
    markdown_text = markdown_path.read_text(encoding="utf-8")
    manifest.update(
        {
            "markdown": markdown_text,
            "markdown_path": str(markdown_path),
            "document_dir": str(document_dir),
            "materials_dir": str(materials_dir),
            "manifest_path": str(manifest_path),
            "descriptions": json.loads(descriptions_path.read_text(encoding="utf-8")) if descriptions_path.exists() else {},
            "description_records": {},
            "asset_catalog": json.loads(asset_catalog_path.read_text(encoding="utf-8")) if asset_catalog_path.exists() else manifest.get("asset_catalog", []),
            "asset_request_contexts": json.loads(request_contexts_path.read_text(encoding="utf-8")) if request_contexts_path.exists() else {},
            "descriptions_path": str(descriptions_path),
            "asset_catalog_path": str(asset_catalog_path),
            "request_contexts_path": str(request_contexts_path),
        }
    )
    return manifest


def _load_existing_slide_briefs(document_dir: Path) -> tuple[dict[str, object], str]:
    slide_briefs_path = document_dir / "ir" / "planned" / "slide_briefs.json"
    if not slide_briefs_path.exists():
        raise FileNotFoundError(f"Missing slide briefs: {slide_briefs_path}")
    slide_briefs = json.loads(slide_briefs_path.read_text(encoding="utf-8"))
    return slide_briefs, str(slide_briefs_path)


def _load_existing_deck_stage(document_dir: Path) -> dict[str, object] | None:
    deck_stage_path = document_dir / "ir" / "planned" / "deck_stage.json"
    if not deck_stage_path.exists():
        return None
    deck_stage = json.loads(deck_stage_path.read_text(encoding="utf-8"))
    if not _has_complete_deck_stage(deck_stage):
        return None
    return deck_stage


def _has_complete_deck_stage(deck_stage: dict[str, object]) -> bool:
    deck_outline = [item for item in deck_stage.get("deck_outline", []) or [] if isinstance(item, dict)]
    if not deck_outline:
        return False

    profile = dict(deck_stage.get("longdoc_profile", {}) or {})
    target_slide_count = int(profile.get("target_slide_count", 0) or 0)
    if target_slide_count > 0 and len(deck_outline) < target_slide_count:
        return False

    return True


def _has_usable_slide_briefs(slide_briefs: dict[str, object] | None) -> bool:
    if not isinstance(slide_briefs, dict):
        return False
    briefs = list(slide_briefs.get("slide_briefs", []) or [])
    brief_count = len(briefs)
    if brief_count == 0:
        return False
    profile = dict(slide_briefs.get("longdoc_profile", {}) or {})
    target_slide_count = int(profile.get("target_slide_count", 0) or 0)
    if target_slide_count > 0:
        minimum_usable_briefs = max(2, (target_slide_count + 1) // 2)
        if brief_count < minimum_usable_briefs:
            return False
    return True


def _load_existing_ir(document_dir: Path, stage: str = "planned") -> dict[str, object] | None:
    bundle_path = document_dir / "ir" / stage / "final_ir.json"
    if not bundle_path.exists():
        return None
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    slides = bundle.get("slides", [])
    material_requests = bundle.get("material_requests", [])
    if not slides:
        return None
    if stage == "planned" and not material_requests:
        return None
    if stage == "planned" and not _has_complete_planned_ir(bundle):
        return None
    return bundle


def _has_complete_planned_ir(ir: dict[str, object]) -> bool:
    slides = [slide for slide in ir.get("slides", []) or [] if isinstance(slide, dict)]
    if not slides:
        return False

    deck_outline = [item for item in ir.get("deck_outline", []) or [] if isinstance(item, dict)]
    if deck_outline:
        slide_ids = {slide.get("slide_id") for slide in slides if slide.get("slide_id")}
        outline_ids = {item.get("slide_id") for item in deck_outline if item.get("slide_id")}
        if outline_ids and not outline_ids.issubset(slide_ids):
            return False
        if len(slides) < len(deck_outline):
            return False

    profile = dict(ir.get("longdoc_profile", {}) or {})
    target_slide_count = int(profile.get("target_slide_count", 0) or 0)
    if target_slide_count > 0 and len(slides) < target_slide_count:
        return False

    return True


def _limit_slide_briefs(slide_briefs: dict[str, object], max_slides: int | None) -> dict[str, object]:
    if max_slides is None or max_slides <= 0:
        return slide_briefs
    limited = copy.deepcopy(slide_briefs)
    briefs = list(limited.get("slide_briefs", []) or [])
    if len(briefs) > max_slides:
        limited["slide_briefs"] = briefs[:max_slides]
    profile = dict(limited.get("longdoc_profile", {}) or {})
    if profile:
        profile["target_slide_count"] = min(int(profile.get("target_slide_count", max_slides)), max_slides)
        notes = list(profile.get("notes", []) or [])
        note = f"Temporarily capped to {max_slides} slides for this run."
        if note not in notes:
            notes.append(note)
        profile["notes"] = notes
        limited["longdoc_profile"] = profile
    return limited


def _limit_ir_slides(ir: dict[str, object], max_slides: int | None) -> dict[str, object]:
    if max_slides is None or max_slides <= 0:
        return ir
    limited = copy.deepcopy(ir)
    slides = list(limited.get("slides", []) or [])
    if len(slides) <= max_slides:
        return limited
    limited_slides = slides[:max_slides]
    limited["slides"] = limited_slides
    allowed_slide_ids = {
        slide.get("slide_id")
        for slide in limited_slides
        if isinstance(slide, dict) and slide.get("slide_id")
    }
    if "deck_outline" in limited:
        deck_outline = list(limited.get("deck_outline", []) or [])
        limited["deck_outline"] = [
            item for item in deck_outline if not isinstance(item, dict) or item.get("slide_id") in allowed_slide_ids
        ]
    material_requests = list(limited.get("material_requests", []) or [])
    filtered_requests = []
    for request in material_requests:
        if not isinstance(request, dict):
            filtered_requests.append(request)
            continue
        request_slide_id = (
            request.get("slide_id")
            or request.get("target_slide_id")
            or request.get("requesting_slide_id")
        )
        if request_slide_id is None or request_slide_id in allowed_slide_ids:
            filtered_requests.append(request)
    limited["material_requests"] = filtered_requests
    return limited


if __name__ == "__main__":
    main()
