from pathlib import Path

import pytest

import cli


class DummyConfig:
    def __init__(self):
        self.language_mode = "english"
        self.complexity_level = "balanced"
        self.model_profile = "general"
        self.max_slides = 0
        self.output_dir = "outputs"
        self.mineru_api_token = "token"
        self.mineru_api_base = "base"
        self.mineru_model_version = "vlm"
        self.mineru_poll_interval = 1
        self.mineru_parse_timeout = 1
        self.llm_api_key = "key"
        self.llm_api_base = "base"
        self.llm_model = "model"
        self.local_llm_api_base = "http://127.0.0.1:18000/v1"
        self.local_llm_model = "local-model"
        self.llm_max_tokens = 0
        self.vlm_api_key = "key"
        self.vlm_api_base = "base"
        self.vlm_model = "model"
        self.planner_max_workers = 1
        self.coder_max_workers = 1
        self.vlm_max_workers = 1
        self.longdoc_chunk_char_limit = 1000
        self.longdoc_overlap_chars = 100
        self.image_api_key = "key"
        self.image_api_base = "base"
        self.image_generation_model = "image-model"


class DummyProgress:
    def __init__(self, *_args, **_kwargs):
        pass

    def start(self, *_args, **_kwargs):
        return None

    def update(self, *_args, **_kwargs):
        return None

    def complete(self, *_args, **_kwargs):
        return None


class DummyParser:
    def __init__(self, *args, **kwargs):
        pass

    def parse(self, pdf_path):
        output_dir = Path("outputs") / "dummy_doc"
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_dir = output_dir / "markdown"
        markdown_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = markdown_dir / "full.md"
        markdown_path.write_text("# dummy", encoding="utf-8")
        images_dir = output_dir / "images" / "self"
        images_dir.mkdir(parents=True, exist_ok=True)
        return {
            "markdown": "# dummy",
            "markdown_path": str(markdown_path),
            "images": [],
            "images_dir": str(images_dir),
            "output_dir": str(output_dir),
        }


class DummyLLMClient:
    init_calls = []

    def __init__(self, *args, **kwargs):
        DummyLLMClient.init_calls.append(kwargs)


class DummyDescriptor:
    def __init__(self, *args, **kwargs):
        pass


class DummyCollector:
    def __init__(self, *args, **kwargs):
        pass

    def collect_with_context(self, output_dir, markdown_text, progress_callback=None):
        materials_dir = Path(output_dir) / "materials"
        materials_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = materials_dir / "material_manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")
        return {
            "markdown": markdown_text,
            "markdown_path": str(Path(output_dir) / "markdown" / "full.md"),
            "materials_dir": str(materials_dir),
            "manifest_path": str(manifest_path),
            "assets": [],
            "images": [],
            "asset_index": {},
        }


class DummyLongDocPlanner:
    last_target_slide_count = None

    def __init__(self, *args, **kwargs):
        pass

    def build_slide_briefs(self, markdown, target_slide_count=None, progress_callback=None):
        DummyLongDocPlanner.last_target_slide_count = target_slide_count
        return {
            "title_hint": "Deck",
            "subtitle_hint": "",
            "storyline_hint": {},
            "planner_notes": [],
            "longdoc_profile": {"chunk_count": 1, "target_slide_count": 1},
            "slide_briefs": [{"slide_id": "slide_01", "title": "Title"}],
        }


class DummySlidePlanner:
    last_init_kwargs = None

    def __init__(self, *args, **kwargs):
        DummySlidePlanner.last_init_kwargs = kwargs

    def plan_deck(self, *args, **kwargs):
        return {
            "title": "Deck",
            "slides": [{"slide_id": "slide_01", "title": "Title", "layout": {"name": "two_column"}, "blocks": [], "visuals": []}],
            "material_requests": [],
        }


class DummyResolver:
    def __init__(self, *args, **kwargs):
        pass

    def resolve(self, materials, ir, progress_callback=None):
        return {"materials": materials, "ir": ir, "resolved_requests": [], "resolution_path": ""}


class DummyArtifactWriter:
    def load_existing_slide_docs(self, *args, **kwargs):
        return []

    def write_single_slide(self, *args, **kwargs):
        return None

    def write_slide_briefs(self, slide_briefs, output_dir, stage="planned"):
        path = Path(output_dir) / "ir" / stage / "slide_briefs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return str(path)

    def write(self, ir, output_dir, stage="planned", slide_briefs=None):
        deck_path = Path(output_dir) / "ir" / stage / "final_ir.json"
        deck_path.parent.mkdir(parents=True, exist_ok=True)
        deck_path.write_text("{}", encoding="utf-8")
        slides_dir = deck_path.parent / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)
        return {"deck_path": str(deck_path), "slides_dir": str(slides_dir), "slide_briefs_path": ""}


class DummyCoder:
    last_init_kwargs = None
    last_mode = None

    def __init__(self, *args, **kwargs):
        DummyCoder.last_init_kwargs = kwargs

    def generate_and_render(self, ir, materials, output_path, mode="library", save_code_path=None, artifact_dir=None, progress_callback=None):
        DummyCoder.last_mode = mode
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("pptx", encoding="utf-8")


class DummyReactRefiner:
    last_init_kwargs = None
    refine_calls = []

    def __init__(self, *args, **kwargs):
        DummyReactRefiner.last_init_kwargs = kwargs

    def refine_deck(self, ir, materials, output_dir, mode="library", progress_callback=None):
        DummyReactRefiner.refine_calls.append(
            {"ir": ir, "materials": materials, "output_dir": output_dir, "mode": mode}
        )
        refined_path = Path(output_dir) / "refined_final.pptx"
        refined_path.write_text("pptx", encoding="utf-8")
        return {"ir": ir, "final_pptx": str(refined_path)}


class DummyTracker:
    def start_step(self, *_args, **_kwargs):
        return None

    def save_to_file(self, path):
        Path(path).write_text("{}", encoding="utf-8")

    def save_to_txt(self, path):
        Path(path).write_text("summary", encoding="utf-8")

    def to_dict(self):
        return {"summary": {"total_llm_tokens": 0, "total_vlm_tokens": 0, "total_image_generations": 0}}


def test_cli_no_react_path_does_not_reference_initial_output_too_early(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    DummyLongDocPlanner.last_target_slide_count = None
    DummySlidePlanner.last_init_kwargs = None
    DummyCoder.last_mode = None
    DummyCoder.last_init_kwargs = None
    DummyLLMClient.init_calls = []
    monkeypatch.setattr(cli, "Config", DummyConfig)
    monkeypatch.setattr(cli, "PipelineProgress", DummyProgress)
    monkeypatch.setattr(cli, "MinerUParser", DummyParser)
    monkeypatch.setattr(cli, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(cli, "VLMDescriptor", DummyDescriptor)
    monkeypatch.setattr(cli, "MaterialCollector", DummyCollector)
    monkeypatch.setattr(cli, "LongDocPlanner", DummyLongDocPlanner)
    monkeypatch.setattr(cli, "SlidePlanner", DummySlidePlanner)
    monkeypatch.setattr(cli, "MaterialResolver", DummyResolver)
    monkeypatch.setattr(cli, "IRArtifactWriter", DummyArtifactWriter)
    monkeypatch.setattr(cli, "PPTXCoder", DummyCoder)
    monkeypatch.setattr(cli, "ImageGenerator", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "reset_global_tracker", lambda: None)
    monkeypatch.setattr(cli, "get_global_tracker", lambda: DummyTracker())
    monkeypatch.setattr(cli.sys, "argv", ["cli.py", "love_yourself.pdf", "--no-react", "--coder-mode", "library", "--output", "final_output.pptx"])

    cli.main()

    assert (tmp_path / "final_output.pptx").exists()
    assert DummyCoder.last_mode == "library"
    assert "library_generation_skill" not in DummyCoder.last_init_kwargs
    assert "qwen_mode" not in DummyCoder.last_init_kwargs
    assert DummyLLMClient.init_calls[0]["model_profile"] == "general"


def test_cli_target_slides_prefers_single_pass_and_library_by_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    DummyLongDocPlanner.last_target_slide_count = None
    DummySlidePlanner.last_init_kwargs = None
    DummyCoder.last_mode = None
    DummyCoder.last_init_kwargs = None
    monkeypatch.setattr(cli, "Config", DummyConfig)
    monkeypatch.setattr(cli, "PipelineProgress", DummyProgress)
    monkeypatch.setattr(cli, "MinerUParser", DummyParser)
    monkeypatch.setattr(cli, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(cli, "VLMDescriptor", DummyDescriptor)
    monkeypatch.setattr(cli, "MaterialCollector", DummyCollector)
    monkeypatch.setattr(cli, "LongDocPlanner", DummyLongDocPlanner)
    monkeypatch.setattr(cli, "SlidePlanner", DummySlidePlanner)
    monkeypatch.setattr(cli, "MaterialResolver", DummyResolver)
    monkeypatch.setattr(cli, "IRArtifactWriter", DummyArtifactWriter)
    monkeypatch.setattr(cli, "PPTXCoder", DummyCoder)
    monkeypatch.setattr(cli, "ImageGenerator", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "reset_global_tracker", lambda: None)
    monkeypatch.setattr(cli, "get_global_tracker", lambda: DummyTracker())
    monkeypatch.setattr(cli.sys, "argv", ["cli.py", "demo.pdf", "--no-react", "--target-slides", "6", "--output", "deck.pptx"])

    cli.main()

    assert (tmp_path / "deck.pptx").exists()
    assert DummyLongDocPlanner.last_target_slide_count == 6
    assert DummySlidePlanner.last_init_kwargs["slide_ir_strategy"] == "single"
    assert DummySlidePlanner.last_init_kwargs["target_slide_count"] == 6
    assert "qwen_mode" not in DummySlidePlanner.last_init_kwargs
    assert DummyCoder.last_mode == "library"
    assert "library_generation_skill" not in DummyCoder.last_init_kwargs
    assert "qwen_mode" not in DummyCoder.last_init_kwargs


def test_cli_qwen_profile_does_not_pass_legacy_combo_knobs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    DummyLongDocPlanner.last_target_slide_count = None
    DummySlidePlanner.last_init_kwargs = None
    DummyCoder.last_mode = None
    DummyCoder.last_init_kwargs = None
    DummyReactRefiner.last_init_kwargs = None
    DummyReactRefiner.refine_calls = []
    DummyLLMClient.init_calls = []
    monkeypatch.setattr(cli, "Config", DummyConfig)
    monkeypatch.setattr(cli, "PipelineProgress", DummyProgress)
    monkeypatch.setattr(cli, "MinerUParser", DummyParser)
    monkeypatch.setattr(cli, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(cli, "VLMDescriptor", DummyDescriptor)
    monkeypatch.setattr(cli, "MaterialCollector", DummyCollector)
    monkeypatch.setattr(cli, "LongDocPlanner", DummyLongDocPlanner)
    monkeypatch.setattr(cli, "SlidePlanner", DummySlidePlanner)
    monkeypatch.setattr(cli, "MaterialResolver", DummyResolver)
    monkeypatch.setattr(cli, "IRArtifactWriter", DummyArtifactWriter)
    monkeypatch.setattr(cli, "PPTXCoder", DummyCoder)
    monkeypatch.setattr(cli, "QwenRecipeCoder", DummyCoder)
    monkeypatch.setattr(cli, "ReactRefiner", DummyReactRefiner)
    monkeypatch.setattr(cli, "ImageGenerator", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "reset_global_tracker", lambda: None)
    monkeypatch.setattr(cli, "get_global_tracker", lambda: DummyTracker())
    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["cli.py", "demo.pdf", "--no-react", "--coder-mode", "library", "--model-profile", "qwen", "--output", "deck.pptx"],
    )

    cli.main()

    assert "qwen_mode" not in DummySlidePlanner.last_init_kwargs
    assert "qwen_mode" not in DummyCoder.last_init_kwargs
    assert "library_generation_skill" not in DummyCoder.last_init_kwargs
    assert DummyCoder.last_mode == "library"


def test_cli_rejects_removed_qwen_mode_argument(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "Config", DummyConfig)
    monkeypatch.setattr(cli, "PipelineProgress", DummyProgress)
    monkeypatch.setattr(cli, "MinerUParser", DummyParser)
    monkeypatch.setattr(cli, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(cli, "VLMDescriptor", DummyDescriptor)
    monkeypatch.setattr(cli, "MaterialCollector", DummyCollector)
    monkeypatch.setattr(cli, "LongDocPlanner", DummyLongDocPlanner)
    monkeypatch.setattr(cli, "SlidePlanner", DummySlidePlanner)
    monkeypatch.setattr(cli, "MaterialResolver", DummyResolver)
    monkeypatch.setattr(cli, "IRArtifactWriter", DummyArtifactWriter)
    monkeypatch.setattr(cli, "PPTXCoder", DummyCoder)
    monkeypatch.setattr(cli, "ReactRefiner", DummyReactRefiner)
    monkeypatch.setattr(cli, "ImageGenerator", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "reset_global_tracker", lambda: None)
    monkeypatch.setattr(cli, "get_global_tracker", lambda: DummyTracker())
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            "demo.pdf",
            "--parse-only",
            "--coder-mode",
            "library",
            "--model-profile",
            "general",
            "--qwen-mode",
            "auto",
            "--output",
            "deck.pptx",
        ],
    )

    with pytest.raises(SystemExit):
        cli.main()


def test_cli_no_longer_exposes_legacy_qwen_library_settings_resolver():
    assert not hasattr(cli, "_resolve_qwen_library_settings")


def test_build_step4_coder_uses_qwen_recipe_coder_for_qwen_library(monkeypatch):
    class DummyQwenRecipeCoder:
        init_args = None
        init_kwargs = None

        def __init__(self, *args, **kwargs):
            DummyQwenRecipeCoder.init_args = args
            DummyQwenRecipeCoder.init_kwargs = kwargs

    monkeypatch.setattr(cli, "QwenRecipeCoder", DummyQwenRecipeCoder)
    config = DummyConfig()
    config.model_profile = "qwen"

    coder = cli._build_step4_coder(
        "library",
        object(),
        config,
    )

    assert isinstance(coder, DummyQwenRecipeCoder)
    assert DummyQwenRecipeCoder.init_kwargs["max_workers"] == config.coder_max_workers
    assert "qwen_mode" not in DummyQwenRecipeCoder.init_kwargs
    assert DummyQwenRecipeCoder.init_kwargs["complexity_level"] == config.complexity_level


def test_build_step5_refiner_uses_qwen_recipe_refiner_for_qwen_library(monkeypatch):
    class DummyQwenRecipeRefiner:
        init_args = None
        init_kwargs = None

        def __init__(self, *args, **kwargs):
            DummyQwenRecipeRefiner.init_args = args
            DummyQwenRecipeRefiner.init_kwargs = kwargs

    monkeypatch.setattr(cli, "QwenRecipeRefiner", DummyQwenRecipeRefiner)
    config = DummyConfig()
    config.model_profile = "qwen"

    refiner = cli._build_step5_refiner(
        "library",
        object(),
        object(),
        object(),
        config,
    )

    assert isinstance(refiner, DummyQwenRecipeRefiner)
    assert DummyQwenRecipeRefiner.init_kwargs["max_iterations"] == 2
    assert DummyQwenRecipeRefiner.init_kwargs["vlm_client"] is not None


def test_resolve_llm_settings_prefers_cli_local_overrides():
    config = DummyConfig()
    config.local_llm_api_base = "http://127.0.0.1:18000/v1"
    config.local_llm_model = "local-default"

    api_base, model = cli._resolve_llm_settings(
        backend="local",
        config=config,
        local_api_base_override="http://127.0.0.1:19000/v1",
        local_model_override="local-override",
    )

    assert api_base == "http://127.0.0.1:19000/v1"
    assert model == "local-override"
