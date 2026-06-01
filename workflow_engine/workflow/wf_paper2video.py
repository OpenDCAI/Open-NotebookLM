"""
paper2video（NotebookLM 嵌入版）

两阶段 API（由 fastapi 分别调用）：
- ``paper2video_subtitle``：PDF → 幻灯片图 → 云 VLM 生成每页脚本（script_pages）
- ``paper2video_continue``：在用户编辑 script_pages 后，refine → 云 TTS → cursor → 合成视频

产物写入 ``Paper2VideoState.result_path``（通常为 ``.../video_pipeline``），最终视频为 ``paper2video.mp4``。
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from workflow_engine.agentroles import create_vlm_agent
from workflow_engine.graphbuilder.graph_builder import GenericGraphBuilder
from workflow_engine.logger import get_logger
from workflow_engine.state import Paper2VideoState
from workflow_engine.workflow.registry import register

log = get_logger(__name__)

MAX_SUBTITLE_RETRIES = 3

# VLM 只需读清幻灯片文字，不必 1080p；降低渲染与 base64 体积，减轻网关压力。
P2V_SLIDE_RENDER_MAX_W = 1280
P2V_SLIDE_RENDER_MAX_H = 720
# 口播/refine 输出为短 JSON；gpt-4o 网关 completion 上限常为 16384，勿用 agent 默认 65536。
P2V_VLM_MAX_TOKENS = 4096


def _work_dir(state: Paper2VideoState) -> Path:
    raw = (getattr(state, "result_path", None) or "").strip()
    if not raw:
        raise ValueError("Paper2VideoState.result_path 未设置（应为 video_pipeline 目录）")
    p = Path(raw).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _render_pdf_slides_fitz(
    pdf_path: str,
    out_dir: Path,
    max_w: int = P2V_SLIDE_RENDER_MAX_W,
    max_h: int = P2V_SLIDE_RENDER_MAX_H,
) -> None:
    """使用 PyMuPDF 将 PDF 每页渲染为 PNG（避免依赖 pdf2image / poppler）。"""
    import fitz

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        for i in range(len(doc)):
            page = doc[i]
            rect = page.rect
            zoom = min(max_w / rect.width, max_h / rect.height)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(out_dir / f"{i + 1}.png"))
    finally:
        doc.close()


@register("paper2video_subtitle")
def create_paper2video_subtitle_graph() -> GenericGraphBuilder:
    """仅阶段一：生成 slide 图 + script_pages。"""

    builder = GenericGraphBuilder(state_model=Paper2VideoState, entry_point="_start_")

    @builder.pre_tool("video_language", "p2v_subtitle_and_cursor")
    def _lang(state: Paper2VideoState):
        return "Chinese" if state.request.language == "zh" else "English"

    async def subtitle_and_cursor(state: Paper2VideoState) -> Paper2VideoState:
        from workflow_engine.toolkits.p2vtool import p2v_tool as P2V

        log.info("paper2video_subtitle: 开始 p2v_subtitle_and_cursor")
        paper_pdf_path = Path(str(state.request.get("paper_pdf_path", "") or "").strip())
        if not paper_pdf_path.is_file():
            log.error("PDF 文件不存在: %s", paper_pdf_path)
            return state

        work = _work_dir(state)
        subtitle_path = work / "subtitle_w_cursor.txt"
        state.subtitle_and_cursor_path = str(subtitle_path)

        slide_img_dir = work / "slide_imgs"
        # PyMuPDF 为同步 CPU/IO，若在 async 节点里直接调用会长时间占用事件循环，
        # 导致 /health 无法响应 → scripts/monitor.sh 误判宕机并 pkill 重启，前端表现为 Failed to fetch。
        await asyncio.to_thread(_render_pdf_slides_fitz, str(paper_pdf_path), slide_img_dir)
        state.slide_img_dir = str(slide_img_dir)

        slide_image_path_list = P2V.get_image_paths(str(slide_img_dir))
        state.subtitle_and_cursor = []

        vlm_model = (getattr(state.request, "model", None) or "gpt-4o").strip()
        for img_idx, img_path in enumerate(slide_image_path_list):
            agent = create_vlm_agent(
                name="p2v_subtitle_and_cursor",
                vlm_mode="understanding",
                image_detail="auto",
                model_name=vlm_model,
                temperature=0.1,
                max_tokens=P2V_VLM_MAX_TOKENS,
                max_image_size=(P2V_SLIDE_RENDER_MAX_W, P2V_SLIDE_RENDER_MAX_H),
                chat_api_url=state.request.chat_api_url,
                additional_params={"input_image": img_path},
            )
            prev_len = len(state.subtitle_and_cursor)
            for attempt in range(MAX_SUBTITLE_RETRIES):
                state = await agent.execute(state=state)
                if len(state.subtitle_and_cursor) > prev_len:
                    break
                log.warning(
                    "第 %s 张 slide 返回格式不符合 JSON，第 %s 次重试",
                    img_idx + 1,
                    attempt + 1,
                )
            else:
                state.subtitle_and_cursor.append("")
                log.warning("第 %s 张 slide 重试后仍失败，使用空占位", img_idx + 1)

        script_pages = []
        for page_num, script_text in enumerate(state.subtitle_and_cursor):
            ip = slide_image_path_list[page_num] if page_num < len(slide_image_path_list) else ""
            script_pages.append({"page_num": page_num, "image_path": ip, "script_text": script_text})
        state.script_pages = script_pages

        meta = {
            "paper_pdf_path": str(paper_pdf_path),
            "slide_img_dir": state.slide_img_dir,
            "subtitle_and_cursor_path": state.subtitle_and_cursor_path,
            "script_pages": script_pages,
        }
        (work / "paper2video_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (work / "script_pages.json").write_text(json.dumps(script_pages, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("paper2video_subtitle: 完成，共 %s 页", len(script_pages))
        return state

    nodes = {
        "_start_": lambda s: s,
        "p2v_subtitle_and_cursor": subtitle_and_cursor,
        "_end_": lambda s: s,
    }
    edges = [
        ("_start_", "p2v_subtitle_and_cursor"),
        ("p2v_subtitle_and_cursor", "_end_"),
    ]
    builder.add_nodes(nodes).add_edges(edges)
    return builder


@register("paper2video_continue")
def create_paper2video_continue_graph() -> GenericGraphBuilder:
    """阶段二：refine → 云 TTS → cursor → merge（无数字人）。"""

    builder = GenericGraphBuilder(state_model=Paper2VideoState, entry_point="_start_")

    @builder.pre_tool("tmp_sentence", "p2v_refine_subtitle_and_cursor")
    def _tmp_sentence(state: Paper2VideoState):
        return state.tmp_sentence

    @builder.pre_tool("video_language", "p2v_refine_subtitle_and_cursor")
    def _video_language(state: Paper2VideoState):
        return "Chinese" if state.request.language == "zh" else "English"

    async def refine_subtitle_and_cursor(state: Paper2VideoState) -> Paper2VideoState:
        from workflow_engine.toolkits.p2vtool import p2v_tool as P2V

        log.info("paper2video_continue: refine_subtitle_and_cursor")
        work = _work_dir(state)
        meta_path = work / "paper2video_meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if not (state.slide_img_dir or "").strip():
                    state.slide_img_dir = str(meta.get("slide_img_dir") or "").strip()
                if not (state.subtitle_and_cursor_path or "").strip():
                    state.subtitle_and_cursor_path = str(meta.get("subtitle_and_cursor_path") or "").strip()
            except Exception as e:
                log.warning("读取 paper2video_meta.json 失败: %s", e)

        subtitle_path = Path(state.subtitle_and_cursor_path or (work / "subtitle_w_cursor.txt"))
        slide_img_dir = state.slide_img_dir or str(work / "slide_imgs")
        script_pages = state.script_pages or []
        if not script_pages:
            meta_path = work / "script_pages.json"
            if meta_path.exists():
                script_pages = json.loads(meta_path.read_text(encoding="utf-8"))
                state.script_pages = script_pages
        sentences = [p.get("script_text", "") for p in script_pages]
        slide_image_path_list = P2V.get_image_paths(slide_img_dir)

        state.subtitle_and_cursor = []
        vlm_model = (getattr(state.request, "model", None) or "gpt-4o").strip()
        for i, img_path in enumerate(slide_image_path_list):
            if i >= len(sentences):
                log.warning("slide 数量多于 script_pages，跳过剩余图片")
                break
            state.tmp_sentence = sentences[i]
            agent = create_vlm_agent(
                name="p2v_refine_subtitle_and_cursor",
                vlm_mode="understanding",
                image_detail="auto",
                model_name=vlm_model,
                temperature=0.1,
                max_tokens=P2V_VLM_MAX_TOKENS,
                max_image_size=(P2V_SLIDE_RENDER_MAX_W, P2V_SLIDE_RENDER_MAX_H),
                chat_api_url=state.request.chat_api_url,
                additional_params={"input_image": img_path},
            )
            prev_len = len(state.subtitle_and_cursor)
            for attempt in range(MAX_SUBTITLE_RETRIES):
                state = await agent.execute(state=state)
                if len(state.subtitle_and_cursor) > prev_len:
                    break
                log.warning("第 %s 张 slide refine 重试 %s", i + 1, attempt + 1)
            else:
                state.subtitle_and_cursor.append((sentences[i] or "").strip() + " | no")

        subtitle_text = "\n###\n".join(state.subtitle_and_cursor)
        state.subtitle_and_cursor_path = str(subtitle_path)
        subtitle_path.write_text(subtitle_text, encoding="utf-8")
        return state

    def generate_speech(state: Paper2VideoState) -> Paper2VideoState:
        from workflow_engine.toolkits.p2vtool import p2v_tool as P2V

        work = _work_dir(state)
        subtitle_path = Path(state.subtitle_and_cursor_path)
        speech_save_dir = work / "audio"
        speech_save_dir.mkdir(parents=True, exist_ok=True)
        state.speech_save_dir = str(speech_save_dir)

        api_key = state.request.api_key
        tts_model = getattr(state.request, "tts_model", None) or "cosyvoice-v3-flash"
        tts_voice_name = (getattr(state.request, "tts_voice_name", None) or "").strip()
        chat_api_url = state.request.chat_api_url
        raw_lang = str(getattr(state.request, "language", None) or "zh").strip().lower()
        tts_language = "en" if raw_lang.startswith("en") else "zh"
        log.info("paper2video_continue: generate_speech（云 TTS, language=%s）", tts_language)

        raw = subtitle_path.read_text(encoding="utf-8")
        parsed = P2V.parse_script_with_cursor(raw)
        slide_timesteps: list = []
        all_tasks = []
        for slide_idx in range(len(parsed)):
            speech_with_cursor = parsed[slide_idx]
            for idx, (prompt, _cursor) in enumerate(speech_with_cursor):
                out_wav = speech_save_dir / f"{slide_idx}_{idx}.wav"
                all_tasks.append(
                    (
                        slide_idx,
                        idx,
                        prompt,
                        str(out_wav),
                        api_key,
                        tts_model,
                        chat_api_url,
                        tts_voice_name,
                        tts_language,
                    )
                )

        max_workers = min(3, len(all_tasks)) if all_tasks else 1
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            results = list(ex.map(P2V.speech_task_wrapper_with_cloud_tts, all_tasks))
        log.info("paper2video_continue: TTS 完成，共 %s 个片段，开始合并每页 wav", len(all_tasks))

        organized: dict = {}
        for s_idx, i_idx, dur, pth in results:
            organized.setdefault(s_idx, {})[i_idx] = (dur, pth)

        for slide_idx in range(len(parsed)):
            slide_speech_path = speech_save_dir / f"{slide_idx}.wav"
            current = sorted(organized[slide_idx].items())
            sentence_duration_list = [data[1][0] for data in current]
            sentence_paths = [data[1][1] for data in current]
            slide_timesteps.append(sentence_duration_list)
            P2V.merge_wav_files(sentence_paths, str(slide_speech_path))
            log.info("paper2video_continue: 已合并 slide %s → %s", slide_idx, slide_speech_path)
            for p in sentence_paths:
                Path(p).unlink(missing_ok=True)

        formatted = [
            {"slide_id": slide_idx, "sentence_duration": [d for d in durations]}
            for slide_idx, durations in enumerate(slide_timesteps)
        ]
        ts_file = speech_save_dir / "slide_timesteps.json"
        ts_file.write_text(json.dumps(formatted, indent=4, ensure_ascii=False), encoding="utf-8")
        state.slide_timesteps_path = str(ts_file)
        log.info("paper2video_continue: generate_speech 完成，timesteps=%s", ts_file)
        return state

    def generate_talking_video(state: Paper2VideoState) -> Paper2VideoState:
        from workflow_engine.toolkits.p2vtool import p2v_tool as P2V

        ref_img_path = (getattr(state.request, "ref_img_path", None) or "").strip()
        if not ref_img_path:
            log.info("ref_img_path 为空，跳过 generate_talking_video")
            return state

        log.info("paper2video_continue: generate_talking_video（LivePortrait）")
        work = _work_dir(state)
        talking_video_save_dir = work / "talking_video"
        state.talking_video_save_dir = str(talking_video_save_dir)
        talking_video_save_dir.mkdir(parents=True, exist_ok=True)

        speech_save_dir = Path(state.speech_save_dir or work / "audio")
        audio_path_list = P2V.get_audio_paths(speech_save_dir)
        talking_inference_input = [[ref_img_path, audio_path] for audio_path in audio_path_list]
        if not talking_inference_input:
            log.warning("无 slide 音频，跳过 talking video")
            return state

        P2V.talking_gen_per_slide(
            "liveportrait",
            talking_inference_input,
            work,
            talking_video_save_dir,
            "",
            api_key=None,
        )
        log.info("paper2video_continue: talking_video 已写入 %s", talking_video_save_dir)
        return state

    def generate_cursor(state: Paper2VideoState) -> Paper2VideoState:
        from workflow_engine.toolkits.p2vtool import p2v_tool as P2V

        log.info("paper2video_continue: generate_cursor")
        work = _work_dir(state)
        subtitle_path = Path(state.subtitle_and_cursor_path)
        slide_img_dir = state.slide_img_dir or str(work / "slide_imgs")
        slide_sentence_timesteps_path = Path(state.slide_timesteps_path)
        cursor_save_path = work / "cursor.json"
        state.cursor_save_path = str(cursor_save_path)

        raw = subtitle_path.read_text(encoding="utf-8")
        parsed = P2V.parse_script_with_cursor(raw)
        slide_image_path_list = P2V.get_image_paths(slide_img_dir)

        task_list = []
        for slide_idx in range(len(parsed)):
            slide_image_path = slide_image_path_list[slide_idx]
            speech_with_cursor = parsed[slide_idx]
            for sentence_idx, (prompt, cursor_prompt) in enumerate(speech_with_cursor):
                task_list.append((slide_idx, sentence_idx, prompt, cursor_prompt, slide_image_path))

        num_workers = min(4, len(task_list)) if task_list else 1
        parallel_tasks = [t + (None,) for t in task_list]
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(processes=num_workers) as pool:
            cursor_result = pool.map(P2V.cursor_infer, parallel_tasks)
        cursor_result.sort(key=lambda x: (x["slide"], x["sentence"]))

        import cv2

        slide_h, slide_w = cv2.imread(slide_image_path_list[0]).shape[:2]
        for index in range(len(cursor_result)):
            if cursor_result[index].get("cursor_prompt") == "no":
                cursor_result[index]["cursor"] = (slide_w // 2, slide_h // 2)

        slide_sentence_timesteps = json.loads(slide_sentence_timesteps_path.read_text(encoding="utf-8"))
        ref_img_path = (getattr(state.request, "ref_img_path", None) or "").strip()
        talking_video_save_dir = state.talking_video_save_dir
        use_talking_for_align = bool(
            ref_img_path and talking_video_save_dir and Path(talking_video_save_dir).is_dir()
        )
        if use_talking_for_align:
            log.info("paper2video_continue: 基于 talking_video 微调每句时长")
            subdirs = sorted(
                [p.name for p in Path(talking_video_save_dir).iterdir() if p.is_dir()],
                key=lambda x: int(x) if str(x).isdigit() else 0,
            )
            for subdir in subdirs:
                talking_video_path = Path(talking_video_save_dir) / subdir / "digit_person_withaudio.mp4"
                try:
                    talking_video_duration = P2V.get_mp4_duration_ffprobe(talking_video_path)
                except Exception:
                    log.warning("读取 talking video 失败: %s", talking_video_path)
                    continue
                slide_id = int(subdir)
                if slide_id >= len(slide_sentence_timesteps):
                    log.warning("跳过文件夹 %s，索引超出范围", subdir)
                    continue
                duration_list = slide_sentence_timesteps[slide_id]["sentence_duration"]
                wav_duration = sum(duration_list)
                num_sentence = len(duration_list) or 1
                bias_us = int(round(talking_video_duration * 1_000_000)) - int(round(wav_duration * 1_000_000))
                per_bias_duration = (bias_us // num_sentence) / 1_000_000.0
                slide_sentence_timesteps[slide_id]["sentence_duration"] = [
                    max(0.0, d + per_bias_duration) for d in duration_list
                ]
            slide_sentence_timesteps_path.write_text(
                json.dumps(slide_sentence_timesteps, indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            log.info("无数字人分支：不进行 talking_video 时间补偿")

        start_time_now = 0.0
        cursor_iter = iter(cursor_result)
        slide_sentence_timesteps_w_cursor = []
        for slide_info in slide_sentence_timesteps:
            slide_idx = slide_info["slide_id"]
            duration_list = slide_info["sentence_duration"]
            for _sentence_idx, duration in enumerate(duration_list):
                start = start_time_now
                end = start + duration
                cursor_info = next(cursor_iter)
                slide_sentence_timesteps_w_cursor.append(
                    {
                        "slide_id": slide_idx,
                        "start": start,
                        "end": end,
                        "text": P2V.clean_text(cursor_info.get("speech_text", "")),
                        "cursor": cursor_info.get("cursor", [slide_w // 2, slide_h // 2]),
                    }
                )
                start_time_now = end

        mid_path = cursor_save_path.with_name(cursor_save_path.name.replace(".json", "_mid.json"))
        mid_path.write_text(json.dumps(cursor_result, indent=2, ensure_ascii=False), encoding="utf-8")
        cursor_save_path.write_text(
            json.dumps(slide_sentence_timesteps_w_cursor, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("paper2video_continue: generate_cursor 完成，%s", cursor_save_path)
        return state

    def merge_all(state: Paper2VideoState) -> Paper2VideoState:
        from workflow_engine.toolkits.p2vtool import p2v_tool as P2V

        log.info("paper2video_continue: merge_all")
        work = _work_dir(state)
        import cv2

        slide_img_dir = Path(state.slide_img_dir or work / "slide_imgs")
        speech_save_dir = Path(state.speech_save_dir or work / "audio")
        cursor_save_path = Path(state.cursor_save_path or work / "cursor.json")
        cursor_img_path = state.request.cursor_path or ""

        tmp_merge_dir = work / "merge"
        tmp_merge_1 = work / "1_merge.mp4"
        tmp_merge_dir.mkdir(parents=True, exist_ok=True)
        image_size = cv2.imread(str(slide_img_dir / "1.png")).shape
        size = max(image_size[0] // 6, image_size[1] // 6)
        width, height = size, size
        num_slide = len(P2V.get_image_paths(str(slide_img_dir)))
        ref_img = (getattr(state.request, "ref_img_path", None) or "").strip()
        talking_save_dir = Path(state.talking_video_save_dir) if state.talking_video_save_dir else None

        if ref_img and talking_save_dir and talking_save_dir.is_dir():
            log.info("paper2video_continue: 使用 talking_video 合并")
            P2V.merge_slides_with_talking_videos(
                slide_img_dir=slide_img_dir,
                talking_video_dir=talking_save_dir,
                merge_dir=tmp_merge_dir,
                output_mp4=tmp_merge_1,
                avatar_width=width,
                avatar_height=height,
                num_slides=num_slide,
            )
        else:
            list_lines = []
            for i in range(num_slide):
                slide_path = slide_img_dir / f"{i + 1}.png"
                wav_path = speech_save_dir / f"{i}.wav"
                if not slide_path.exists() or not wav_path.exists():
                    log.warning("跳过 page %s: 缺少 %s 或 %s", i, slide_path, wav_path)
                    continue
                duration = P2V.get_audio_length(str(wav_path))
                output_path = tmp_merge_dir / f"page_{i:03d}.mp4"
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-t",
                    str(duration),
                    "-i",
                    str(slide_path),
                    "-i",
                    str(wav_path),
                    "-filter_complex",
                    "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2[v]",
                    "-map",
                    "[v]",
                    "-map",
                    "1:a",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "23",
                    "-shortest",
                    str(output_path),
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                list_lines.append(f"file '{output_path.resolve()}'")

            list_file = tmp_merge_dir / "list.txt"
            list_file.write_text("\n".join(list_lines), encoding="utf-8")
            if not list_lines:
                raise RuntimeError("无有效 slide/语音片段可供合并")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(tmp_merge_1)],
                check=True,
                capture_output=True,
                text=True,
            )

        cursor_size = max(size // 6, 8)
        tmp_merge_2 = work / "2_merge.mp4"
        P2V.render_video_with_cursor_from_json(
            video_path=str(tmp_merge_1),
            out_video_path=str(tmp_merge_2),
            json_path=str(cursor_save_path),
            cursor_img_path=cursor_img_path,
            transition_duration=0.1,
            cursor_size=cursor_size,
        )
        font_size = max(size // 10, 12)
        final_mp4 = work / "paper2video.mp4"
        P2V.add_subtitles(str(tmp_merge_2), str(final_mp4), str(cursor_save_path), font_size)
        state.video_path = str(final_mp4)
        log.info("paper2video 完成: %s", final_mp4)
        return state

    def _after_speech_condition(state: Paper2VideoState) -> str:
        ref_img_path = (getattr(state.request, "ref_img_path", None) or "").strip()
        if ref_img_path:
            return "p2v_generate_talking_video"
        return "p2v_generate_cursor"

    nodes = {
        "_start_": lambda s: s,
        "p2v_refine_subtitle_and_cursor": refine_subtitle_and_cursor,
        "p2v_generate_speech": generate_speech,
        "p2v_generate_talking_video": generate_talking_video,
        "p2v_generate_cursor": generate_cursor,
        "p2v_merge": merge_all,
        "_end_": lambda s: s,
    }
    edges = [
        ("_start_", "p2v_refine_subtitle_and_cursor"),
        ("p2v_refine_subtitle_and_cursor", "p2v_generate_speech"),
        ("p2v_generate_talking_video", "p2v_generate_cursor"),
        ("p2v_generate_cursor", "p2v_merge"),
        ("p2v_merge", "_end_"),
    ]
    builder.add_nodes(nodes).add_edges(edges)
    builder.add_conditional_edges({"p2v_generate_speech": _after_speech_condition})
    return builder
