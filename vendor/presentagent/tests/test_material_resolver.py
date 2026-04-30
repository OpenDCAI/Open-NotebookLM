import httpx

from src.materials.material_resolver import MaterialResolver


class TimeoutImageGenerator:
    async def generate_image(self, *args, **kwargs):
        raise httpx.ReadTimeout("paper2any timed out")


class NoopDescriptor:
    pass


def test_material_resolver_records_paper2any_timeout_without_crashing(tmp_path):
    resolver = MaterialResolver(
        descriptor=NoopDescriptor(),
        image_generator=TimeoutImageGenerator(),
    )
    materials = {
        "document_dir": str(tmp_path),
        "markdown": "",
        "assets": [],
        "descriptions": {},
    }
    request = {
        "request_id": "req_timeout",
        "asset_type": "image",
        "target_slide_id": "slide_01",
        "caption": "Generate a stable presentation visual",
        "minimum_vlm_score": 0.7,
        "acquisition_plan": {"source_options": ["paper2any"]},
    }

    _, resolution = resolver._resolve_single_request(
        materials,
        request,
        used_asset_ids=set(),
        document_dir=tmp_path,
    )

    assert resolution["resolution_status"] == "unresolved"
    assert resolution["matched_from"] == "none"
    assert resolution["attempts"][0]["status"] == "generation_failed"
    assert "ReadTimeout" in resolution["attempts"][0]["error"]
