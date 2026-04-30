"""Material collection skill for IR refinement agent."""

from pathlib import Path
from typing import Any, Dict


class MaterialCollectionSkill:
    """Skill: Collect and validate materials (images/icons) based on request."""

    name = "collect_material"
    description = "Collect new image or icon based on material request. Use when current visual is inappropriate or missing."

    def __init__(self, material_resolver):
        """Initialize with MaterialResolver dependency."""
        self.material_resolver = material_resolver

    def execute(
        self,
        material_request: Dict[str, Any],
        materials: Dict[str, Any],
        document_dir: str,
        used_asset_ids: set[str] | None = None,
    ) -> Dict[str, Any]:
        """Execute material collection.

        Args:
            material_request: {
                "request_id": str,
                "asset_type": "image" | "icon",
                "caption": str,
                "purpose": str,
                "size_preference": "small" | "medium" | "large" | "hero",
                "orientation_preference": "landscape" | "portrait" | "square" | "any",
                "minimum_vlm_score": float
            }
            materials: Current materials dict
            document_dir: Document directory path
            used_asset_ids: Set of already used asset IDs

        Returns:
            {
                "success": bool,
                "updated_materials": dict,
                "selected_candidate": dict | None,
                "resolution": dict
            }
        """
        used_asset_ids = used_asset_ids or set()

        # Call MaterialResolver
        updated_materials, resolution = self.material_resolver._resolve_single_request(
            materials,
            material_request,
            used_asset_ids,
            Path(document_dir),
        )

        resolved_candidate = resolution.get("resolved_candidate")
        success = resolution.get("resolution_status") == "resolved"

        return {
            "success": success,
            "updated_materials": updated_materials,
            "selected_candidate": resolved_candidate,
            "resolution": resolution,
        }
