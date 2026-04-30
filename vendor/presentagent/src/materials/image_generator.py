"""Text-to-image generation adapted from Paper2Any."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from ..utils.token_tracker import get_global_tracker


class ImageGenerator:
    """Minimal provider-aware image generator copied from Paper2Any patterns."""

    COMFLY_MODEL_MAPPING = {
        "gemini-2.5-flash-image": "nano-banana",
        "gemini-2.5-flash-image-preview": "nano-banana",
        "gemini-3-pro-image-preview": "nano-banana-2-2k",
        "gemini-3.1-flash-image-preview": "nano-banana-2-2k",
    }

    def __init__(self, api_key: str, api_base: str, model: str = "gemini-3.1-flash-image-preview"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model

    async def generate_image(
        self,
        prompt: str,
        output_path: str,
        *,
        asset_type: str = "image",
        aspect_ratio: str = "16:9",
        resolution: str = "1K",
        quality: str = "standard",
        style: str = "vivid",
        response_format: str = "b64_json",
        timeout: int = 600,
    ) -> str:
        # For icons, enhance prompt with transparent/blurred background requirement
        if asset_type == "icon":
            prompt = f"{prompt}. IMPORTANT: Clean flat icon style with transparent or blurred background, minimal design, suitable for presentation slides."

        request_type, url, payload = self._build_generation_request(
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            quality=quality,
            style=style,
            response_format=response_format,
        )
        headers = self._build_headers(request_type)

        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            resp_data = resp.json()

            image_ref = self._parse_generation_response(request_type, resp_data)
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            if image_ref.startswith("http"):
                image_resp = await client.get(image_ref)
                image_resp.raise_for_status()
                output_file.write_bytes(image_resp.content)
            else:
                output_file.write_bytes(base64.b64decode(image_ref))

        # Track image generation
        tracker = get_global_tracker()
        tracker.add_image_generation(1)

        return str(output_file)

    def _build_generation_request(
        self,
        *,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
        quality: str,
        style: str,
        response_format: str,
    ) -> tuple[str, str, dict[str, Any]]:
        if self._uses_native_gemini_image_api():
            url = f"{self._base_root()}/v1beta/models/{self.model}:generateContent"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": self._build_native_gemini_prompt(
                                    prompt=prompt,
                                    aspect_ratio=aspect_ratio,
                                    resolution=resolution,
                                    quality=quality,
                                    style=style,
                                )
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                    "imageConfig": {
                        "aspectRatio": aspect_ratio,
                        "imageSize": resolution,
                    },
                },
            }
            return "gemini_native", url, payload

        url = f"{self.api_base}/images/generations"
        model = self._translate_model_name(self.model)
        payload = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": self._aspect_ratio_to_size(aspect_ratio, resolution),
            "quality": quality,
            "response_format": response_format,
        }
        if model.lower().startswith("dall-e"):
            payload["style"] = style
        return "openai_images", url, payload

    def _build_headers(self, request_type: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if request_type == "gemini_native":
            headers["Authorization"] = f"Bearer {self.api_key}"
            return headers
        headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _translate_model_name(self, model: str) -> str:
        if "comfly.chat" in self.api_base.lower():
            return self.COMFLY_MODEL_MAPPING.get(model, model)
        return model

    def _uses_native_gemini_image_api(self) -> bool:
        base = self.api_base.lower()
        return self.model.lower().startswith("gemini-") and "comfly.chat" not in base

    def _base_root(self) -> str:
        base = self.api_base.rstrip("/")
        if base.endswith("/v1"):
            return base[:-3]
        return base

    @staticmethod
    def _build_native_gemini_prompt(
        *,
        prompt: str,
        aspect_ratio: str,
        resolution: str,
        quality: str,
        style: str,
    ) -> str:
        return (
            f"{prompt}\n"
            f"Aspect ratio preference: {aspect_ratio}.\n"
            f"Resolution target: {resolution}.\n"
            f"Quality level: {quality}.\n"
            f"Visual style: {style}.\n"
            "Return one presentation-ready image only."
        )

    @staticmethod
    def _parse_generation_response(request_type: str, data: dict[str, Any]) -> str:
        if request_type == "gemini_native":
            for candidate in data.get("candidates", []):
                content = candidate.get("content", {}) or {}
                parts = content.get("parts", [])
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    inline = part.get("inlineData") or {}
                    image_data = inline.get("data")
                    if image_data:
                        return image_data
            finish_reasons = [
                str(candidate.get("finishReason") or "").strip()
                for candidate in data.get("candidates", [])
                if str(candidate.get("finishReason") or "").strip()
            ]
            reason = f" finishReason={','.join(finish_reasons)};" if finish_reasons else ""
            raise RuntimeError(
                f"Failed to parse Gemini image generation response:{reason} expected inlineData.data; {str(data)[:400]}"
            )

        if "data" in data and data["data"]:
            item = data["data"][0]
            if "b64_json" in item:
                return item["b64_json"]
            if "url" in item:
                return item["url"]
        raise RuntimeError(f"Failed to parse image generation response: {str(data)[:200]}")

    @staticmethod
    def _resolution_to_size(resolution: str) -> str:
        """Convert resolution string to Gemini imageSize format."""
        resolution_map = {
            "512": "512",
            "1K": "1024",
            "2K": "2048",
            "4K": "4096",
        }
        return resolution_map.get(resolution, "2048")

    @staticmethod
    def _aspect_ratio_to_size(aspect_ratio: str, resolution: str = "2K") -> str:
        resolution_map = {
            "512": 512,
            "1K": 1024,
            "2K": 2048,
            "4K": 4096,
        }
        base = resolution_map.get(resolution, 2048)
        if ":" not in aspect_ratio:
            return "1024x1024"
        try:
            w_ratio, h_ratio = map(int, aspect_ratio.split(":"))
            if w_ratio > h_ratio:
                width = base
                height = int(base * h_ratio / w_ratio)
            elif w_ratio < h_ratio:
                height = base
                width = int(base * w_ratio / h_ratio)
            else:
                width = height = base
            return f"{width}x{height}"
        except (ValueError, ZeroDivisionError):
            return "1024x1024"
