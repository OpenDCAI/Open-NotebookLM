from pathlib import Path
import subprocess

from vendor.presentagent.src.utils.config import Config
from fastapi_app.services.editable_ppt_service import EditablePPTService


def test_qwen_defaults_to_library_mode_when_coder_mode_is_omitted(tmp_path: Path) -> None:
    service = EditablePPTService(
        presentagent_root=tmp_path,
        project_root=tmp_path,
        python_bin="python",
    )

    options = service.normalize_request(
        model_profile="qwen",
        coder_mode=None,
        language="chinese",
        complexity="complex",
        target_slides=6,
        api_url="",
        api_key="",
        model="",
    )

    assert options["model_profile"] == "qwen"
    assert options["coder_mode"] == "library"


def test_qwen_library_and_direct_modes_build_local_qwen_command(tmp_path: Path) -> None:
    service = EditablePPTService(
        presentagent_root=tmp_path,
        project_root=tmp_path,
        python_bin="python",
    )

    library_options = service.normalize_request(
        model_profile="qwen",
        coder_mode="library",
        language="chinese",
        complexity="complex",
        target_slides=6,
        api_url="https://ignored.example/v1",
        api_key="ignored",
        model="ignored-model",
    )
    direct_options = dict(library_options, coder_mode="direct")

    library_command = service._build_command(
        input_path="paper.pdf",
        output_path=tmp_path / "library.pptx",
        options=library_options,
    )
    direct_command = service._build_command(
        input_path="paper.pdf",
        output_path=tmp_path / "direct.pptx",
        options=direct_options,
    )

    assert library_command[library_command.index("--coder-mode") + 1] == "library"
    assert direct_command[direct_command.index("--coder-mode") + 1] == "direct"
    assert library_command[library_command.index("--model-profile") + 1] == "qwen"
    assert library_command[library_command.index("--llm-backend") + 1] == "local"
    assert "--qwen-mode" not in library_command
    assert "--qwen-mode" not in direct_command
    assert "--local-llm-api-base" not in library_command
    assert "--local-llm-model" not in library_command


def test_run_presentagent_normalizes_pptx_for_onlyoffice(tmp_path: Path, monkeypatch) -> None:
    presentagent_root = tmp_path / "presentagent"
    presentagent_root.mkdir()
    (presentagent_root / "cli.py").write_text("print('stub')", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_which(name: str) -> str:
        return "/usr/bin/libreoffice" if name == "libreoffice" else ""

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        if command[0] == "python":
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_bytes(b"raw pptx")
            return subprocess.CompletedProcess(command, 0, stdout="generated")
        if command[0] == "/usr/bin/libreoffice":
            outdir = Path(command[command.index("--outdir") + 1])
            source = Path(command[-1])
            (outdir / source.name).write_bytes(b"normalized pptx")
            return subprocess.CompletedProcess(command, 0, stdout="converted")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr("fastapi_app.services.editable_ppt_service.shutil.which", fake_which)
    monkeypatch.setattr("fastapi_app.services.editable_ppt_service.subprocess.run", fake_run)

    service = EditablePPTService(
        presentagent_root=presentagent_root,
        project_root=tmp_path,
        python_bin="python",
    )
    result = service.run_presentagent(
        input_path=str(tmp_path / "source.pdf"),
        output_dir=tmp_path / "output",
        title="Deck",
        model_profile="general",
        coder_mode="library",
        language="chinese",
        complexity="balanced",
        target_slides=3,
        api_url="",
        api_key="",
        model="",
    )

    pptx_path = Path(result["pptx_path"])
    assert pptx_path.read_bytes() == b"normalized pptx"
    assert result["onlyoffice_normalized"] is True
    assert any(call[0] == "/usr/bin/libreoffice" for call in calls)


def test_presentagent_config_defaults_do_not_embed_real_api_keys(monkeypatch) -> None:
    monkeypatch.delenv("PRESENT_AGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("PRESENT_AGENT_VLM_API_KEY", raising=False)
    monkeypatch.delenv("PRESENT_AGENT_IMAGE_API_KEY", raising=False)

    config = Config()

    assert not config.llm_api_key.startswith("sk-")
    assert not config.vlm_api_key.startswith("sk-")
    assert not config.image_api_key.startswith("sk-")
    assert not config.mineru_api_token.startswith("eyJ")
