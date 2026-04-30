from __future__ import annotations

from pathlib import Path
import asyncio
import json

import pytest

from fastapi_app.config.settings import settings
from fastapi_app.services.output_v2_service import OutputV2Service


def test_create_outline_supports_editable_ppt_without_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = OutputV2Service()
    monkeypatch.setattr(service, "_base_dir", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(service, "_maybe_load_document", lambda **kwargs: {"id": "", "title": "", "content": ""})
    monkeypatch.setattr(service, "_load_guidance_items", lambda **kwargs: [])
    monkeypatch.setattr(service, "_load_bound_documents", lambda **kwargs: [])

    item = asyncio.run(service.create_outline(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        document_id="",
        target_type="editable_ppt",
        title="Editable Deck",
        prompt="",
        page_count=8,
        source_paths=["/tmp/source.pdf"],
        source_names=["source.pdf"],
    ))

    assert item["target_type"] == "editable_ppt"
    assert item["status"] == "ready"
    assert item["pipeline_stage"] == "ready"
    assert item["result"]["mode_defaults"]["react_enabled"] is True
    assert item["source_paths"] == ["/tmp/source.pdf"]


def test_generate_output_dispatches_editable_ppt_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = OutputV2Service()
    monkeypatch.setattr(service, "_base_dir", lambda *args, **kwargs: tmp_path)
    monkeypatch.setattr(service, "_maybe_load_document", lambda **kwargs: {"id": "", "title": "", "content": "# Doc"})
    monkeypatch.setattr(service, "_load_guidance_items", lambda **kwargs: [])

    manifest_path = tmp_path / "items.json"
    output_id = "out_editable"
    item_dir = tmp_path / output_id
    item_dir.mkdir()
    service._write_manifest(
        manifest_path,
        [
            {
                "id": output_id,
                "document_id": "",
                "title": "Editable Deck",
                "target_type": "editable_ppt",
                "status": "ready",
                "pipeline_stage": "ready",
                "outline": [],
                "page_count": 8,
                "source_paths": ["/tmp/source.pdf"],
                "source_names": ["source.pdf"],
                "guidance_item_ids": [],
                "created_at": service._now(),
                "updated_at": service._now(),
                "result": {},
                "result_path": str(item_dir),
            }
        ],
    )

    calls: list[dict[str, object]] = []

    class FakeEditablePPTService:
        def run_from_output(self, **kwargs):
            calls.append(kwargs)
            return {
                "pptx_url": "/outputs/local/notebook/out_editable/editable.pptx",
                "pptx_path": str(item_dir / "editable.pptx"),
                "deck_ir": {"title": "Editable Deck", "slides": []},
                "slide_count": 0,
            }

    monkeypatch.setattr(
        "fastapi_app.services.output_v2_service.EditablePPTService",
        FakeEditablePPTService,
        raising=False,
    )

    item = asyncio.run(service.generate_output(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        email="local",
        output_id=output_id,
        api_url="https://api.example.test/v1",
        api_key="sk-test",
        model="claude-sonnet-4-6",
    ))

    assert calls
    assert calls[0]["item"]["id"] == output_id
    assert calls[0]["document"]["content"] == "# Doc"
    assert item["status"] == "generated"
    assert item["pipeline_stage"] == "generated"
    assert item["result"]["pptx_url"].endswith("editable.pptx")


def test_list_outputs_hydrates_editable_ppt_ir_from_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = OutputV2Service()
    monkeypatch.setattr(service, "_base_dir", lambda *args, **kwargs: tmp_path)

    output_id = "out_editable"
    item_dir = tmp_path / output_id
    slides_dir = item_dir / "editable_ppt_resume" / "paper" / "ir" / "refined" / "slides"
    slides_dir.mkdir(parents=True)
    (item_dir / "editable.pptx").write_bytes(b"pptx")
    (item_dir / "editable_ppt_resume" / "paper" / "ir" / "refined" / "final_ir.json").write_text(
        json.dumps({"title": "Editable Deck"}),
        encoding="utf-8",
    )
    (slides_dir / "slide_01.json").write_text(json.dumps({"title": "Slide 1"}), encoding="utf-8")

    service._write_manifest(
        tmp_path / "items.json",
        [
            {
                "id": output_id,
                "document_id": "",
                "title": "Editable Deck",
                "target_type": "editable_ppt",
                "status": "generated",
                "pipeline_stage": "generated",
                "outline": [],
                "page_count": 8,
                "source_paths": [],
                "source_names": [],
                "guidance_item_ids": [],
                "created_at": service._now(),
                "updated_at": service._now(),
                "result": {
                    "pptx_path": str(item_dir / "editable.pptx"),
                    "pptx_url": "/outputs/local/notebook/out_editable/editable.pptx",
                    "deck_ir": {},
                    "slide_count": 0,
                },
                "result_path": str(item_dir),
            }
        ],
    )

    outputs = service.list_outputs(notebook_id="nb1", notebook_title="Notebook", user_id="local")

    hydrated = outputs[0]["result"]
    assert hydrated["deck_ir"]["title"] == "Editable Deck"
    assert hydrated["deck_ir"]["slides"] == [{"title": "Slide 1"}]
    assert hydrated["slide_irs"] == [{"title": "Slide 1"}]
    assert hydrated["slide_count"] == 1


def test_onlyoffice_config_uses_editable_pptx_and_callback_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ONLYOFFICE_DOCUMENT_SERVER_URL", "http://onlyoffice.local")
    monkeypatch.setattr(settings, "ONLYOFFICE_THINKFLOW_PUBLIC_URL", "https://thinkflow.example.test")
    monkeypatch.setattr(settings, "ONLYOFFICE_DOCUMENT_DOWNLOAD_BASE_URL", "")
    service = OutputV2Service()
    monkeypatch.setattr(service, "_base_dir", lambda *args, **kwargs: tmp_path)

    output_id = "out_editable"
    item_dir = tmp_path / output_id
    item_dir.mkdir()
    pptx_path = item_dir / "editable.pptx"
    pptx_path.write_bytes(b"pptx")
    service._write_manifest(
        tmp_path / "items.json",
        [
            {
                "id": output_id,
                "document_id": "",
                "title": "Editable Deck",
                "target_type": "editable_ppt",
                "status": "generated",
                "pipeline_stage": "generated",
                "outline": [],
                "page_count": 8,
                "source_paths": [],
                "source_names": [],
                "guidance_item_ids": [],
                "created_at": service._now(),
                "updated_at": service._now(),
                "result": {"pptx_path": str(pptx_path), "pptx_url": "/outputs/local/notebook/out_editable/editable.pptx"},
                "result_path": str(item_dir),
            }
        ],
    )

    payload = service.get_onlyoffice_config(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        output_id=output_id,
        request_base_url="http://127.0.0.1:8000",
        browser_base_url="http://localhost:3003",
    )

    assert payload["enabled"] is True
    assert payload["document_server_url"] == "http://onlyoffice.local"
    assert payload["script_url"] == "http://onlyoffice.local/web-apps/apps/api/documents/api.js"
    assert payload["config"]["documentType"] == "slide"
    assert payload["config"]["document"]["fileType"] == "pptx"
    assert payload["config"]["document"]["url"].startswith(
        "http://localhost:3003/api/v1/kb/outputs/out_editable/onlyoffice/download/"
    )
    assert "x_api_key" not in payload["config"]["document"]["url"]
    assert "X-API-Key" not in payload["config"]["document"]["url"]
    assert "df-internal-2024-workflow-key" not in payload["config"]["document"]["url"]
    assert payload["config"]["document"]["url"].endswith(
        ".pptx?notebook_id=nb1&notebook_title=Notebook&user_id=local"
        "&document_base_url=http%3A%2F%2Flocalhost%3A3003"
    )
    assert len(payload["config"]["document"]["key"]) == 40
    assert "/onlyoffice/callback" in payload["config"]["editorConfig"]["callbackUrl"]
    assert payload["config"]["editorConfig"]["callbackUrl"].startswith("https://thinkflow.example.test/")
    assert "x_api_key" not in payload["config"]["editorConfig"]["callbackUrl"]
    assert "X-API-Key" not in payload["config"]["editorConfig"]["callbackUrl"]
    assert "df-internal-2024-workflow-key" not in payload["config"]["editorConfig"]["callbackUrl"]


def test_onlyoffice_config_prefers_browser_download_base_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ONLYOFFICE_DOCUMENT_SERVER_URL", "http://onlyoffice.local")
    monkeypatch.setattr(settings, "ONLYOFFICE_THINKFLOW_PUBLIC_URL", "https://thinkflow.example.test")
    monkeypatch.setattr(settings, "ONLYOFFICE_DOCUMENT_DOWNLOAD_BASE_URL", "http://172.18.0.1:3003")
    service = OutputV2Service()
    monkeypatch.setattr(service, "_base_dir", lambda *args, **kwargs: tmp_path)

    output_id = "out_editable"
    item_dir = tmp_path / output_id
    item_dir.mkdir()
    pptx_path = item_dir / "editable.pptx"
    pptx_path.write_bytes(b"pptx")
    service._write_manifest(
        tmp_path / "items.json",
        [
            {
                "id": output_id,
                "document_id": "",
                "title": "Editable Deck",
                "target_type": "editable_ppt",
                "status": "generated",
                "pipeline_stage": "generated",
                "outline": [],
                "page_count": 8,
                "source_paths": [],
                "source_names": [],
                "guidance_item_ids": [],
                "created_at": service._now(),
                "updated_at": service._now(),
                "result": {"pptx_path": str(pptx_path), "pptx_url": "/outputs/local/notebook/out_editable/editable.pptx"},
                "result_path": str(item_dir),
            }
        ],
    )

    payload = service.get_onlyoffice_config(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        output_id=output_id,
        request_base_url="http://127.0.0.1:8000",
        browser_base_url="http://localhost:3003",
    )

    assert payload["config"]["document"]["url"].startswith(
        "http://localhost:3003/api/v1/kb/outputs/out_editable/onlyoffice/download/"
    )
    assert "document_base_url=http%3A%2F%2Flocalhost%3A3003" in payload["config"]["document"]["url"]
    assert payload["config"]["editorConfig"]["callbackUrl"].startswith("https://thinkflow.example.test/")


def test_onlyoffice_document_key_changes_when_download_base_url_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ONLYOFFICE_DOCUMENT_SERVER_URL", "http://onlyoffice.local")
    monkeypatch.setattr(settings, "ONLYOFFICE_THINKFLOW_PUBLIC_URL", "https://thinkflow.example.test")
    service = OutputV2Service()
    monkeypatch.setattr(service, "_base_dir", lambda *args, **kwargs: tmp_path)

    output_id = "out_editable"
    item_dir = tmp_path / output_id
    item_dir.mkdir()
    pptx_path = item_dir / "editable.pptx"
    pptx_path.write_bytes(b"pptx")
    service._write_manifest(
        tmp_path / "items.json",
        [
            {
                "id": output_id,
                "document_id": "",
                "title": "Editable Deck",
                "target_type": "editable_ppt",
                "status": "generated",
                "pipeline_stage": "generated",
                "outline": [],
                "page_count": 8,
                "source_paths": [],
                "source_names": [],
                "guidance_item_ids": [],
                "created_at": service._now(),
                "updated_at": service._now(),
                "result": {"pptx_path": str(pptx_path), "pptx_url": "/outputs/local/notebook/out_editable/editable.pptx"},
                "result_path": str(item_dir),
            }
        ],
    )

    monkeypatch.setattr(settings, "ONLYOFFICE_DOCUMENT_DOWNLOAD_BASE_URL", "http://172.18.0.1:3003")
    gateway_payload = service.get_onlyoffice_config(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        output_id=output_id,
        request_base_url="http://127.0.0.1:8000",
        browser_base_url="http://127.0.0.1:3003",
    )

    monkeypatch.setattr(settings, "ONLYOFFICE_DOCUMENT_DOWNLOAD_BASE_URL", "http://localhost:3003")
    localhost_payload = service.get_onlyoffice_config(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        output_id=output_id,
        request_base_url="http://127.0.0.1:8000",
        browser_base_url="http://localhost:3003",
    )

    assert gateway_payload["config"]["document"]["url"].startswith("http://127.0.0.1:3003/")
    assert localhost_payload["config"]["document"]["url"].startswith("http://localhost:3003/")
    assert gateway_payload["config"]["document"]["key"] != localhost_payload["config"]["document"]["key"]


def test_onlyoffice_document_key_changes_per_editor_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ONLYOFFICE_DOCUMENT_SERVER_URL", "http://onlyoffice.local")
    monkeypatch.setattr(settings, "ONLYOFFICE_THINKFLOW_PUBLIC_URL", "https://thinkflow.example.test")
    monkeypatch.setattr(settings, "ONLYOFFICE_DOCUMENT_DOWNLOAD_BASE_URL", "")
    service = OutputV2Service()
    monkeypatch.setattr(service, "_base_dir", lambda *args, **kwargs: tmp_path)

    output_id = "out_editable"
    item_dir = tmp_path / output_id
    item_dir.mkdir()
    pptx_path = item_dir / "editable.pptx"
    pptx_path.write_bytes(b"pptx")
    service._write_manifest(
        tmp_path / "items.json",
        [
            {
                "id": output_id,
                "document_id": "",
                "title": "Editable Deck",
                "target_type": "editable_ppt",
                "status": "generated",
                "pipeline_stage": "generated",
                "outline": [],
                "page_count": 8,
                "source_paths": [],
                "source_names": [],
                "guidance_item_ids": [],
                "created_at": service._now(),
                "updated_at": service._now(),
                "result": {"pptx_path": str(pptx_path), "pptx_url": "/outputs/local/notebook/out_editable/editable.pptx"},
                "result_path": str(item_dir),
            }
        ],
    )

    first_payload = service.get_onlyoffice_config(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        output_id=output_id,
        request_base_url="http://127.0.0.1:8000",
        browser_base_url="http://localhost:3003",
        editor_session_id="session-a",
    )
    second_payload = service.get_onlyoffice_config(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        output_id=output_id,
        request_base_url="http://127.0.0.1:8000",
        browser_base_url="http://localhost:3003",
        editor_session_id="session-b",
    )

    assert first_payload["config"]["document"]["key"] != second_payload["config"]["document"]["key"]
    assert "editor_session_id=session-a" in first_payload["config"]["document"]["url"]
    assert "editor_session_id=session-b" in second_payload["config"]["document"]["url"]


def test_onlyoffice_callback_saves_returned_pptx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = OutputV2Service()
    monkeypatch.setattr(service, "_base_dir", lambda *args, **kwargs: tmp_path)

    output_id = "out_editable"
    item_dir = tmp_path / output_id
    item_dir.mkdir()
    pptx_path = item_dir / "editable.pptx"
    pptx_path.write_bytes(b"old")
    manifest_path = tmp_path / "items.json"
    service._write_manifest(
        manifest_path,
        [
            {
                "id": output_id,
                "document_id": "",
                "title": "Editable Deck",
                "target_type": "editable_ppt",
                "status": "generated",
                "pipeline_stage": "generated",
                "outline": [],
                "page_count": 8,
                "source_paths": [],
                "source_names": [],
                "guidance_item_ids": [],
                "created_at": service._now(),
                "updated_at": service._now(),
                "result": {"pptx_path": str(pptx_path)},
                "result_path": str(item_dir),
            }
        ],
    )
    item = service._read_manifest(manifest_path)[0]
    expected_key = service._onlyoffice_document_key(
        pptx_path,
        output_id=output_id,
        item=item,
        document_base_url="http://localhost:3003",
        editor_session_id="session-1",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"new pptx"

    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=60: FakeResponse())

    result = service.handle_onlyoffice_callback(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        output_id=output_id,
        payload={
            "status": 2,
            "url": "http://onlyoffice.local/cache/file.pptx",
            "key": expected_key,
        },
        document_base_url="http://localhost:3003",
        editor_session_id="session-1",
    )

    assert result == {"error": 0}
    assert pptx_path.read_bytes() == b"new pptx"
    updated = service._read_manifest(manifest_path)[0]
    assert updated["result"]["onlyoffice_saved_at"]

    rejected = service.handle_onlyoffice_callback(
        notebook_id="nb1",
        notebook_title="Notebook",
        user_id="local",
        output_id=output_id,
        payload={
            "status": 2,
            "url": "http://onlyoffice.local/cache/file.pptx",
            "key": "wrong",
        },
        document_base_url="http://localhost:3003",
        editor_session_id="session-1",
    )
    assert rejected == {"error": 1}
