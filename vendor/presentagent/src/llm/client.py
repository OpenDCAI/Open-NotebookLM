"""LLM client wrapper."""
import os
from typing import Any, List, Dict

from ..utils.token_tracker import get_global_tracker

class LLMClient:
    def __init__(
        self,
        api_key: str,
        api_base: str,
        model: str,
        client_type: str = "llm",
        model_profile: str = "general",
    ):
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError("Missing openai dependency. Install requirements.txt first.") from exc
        timeout_seconds = self._resolve_timeout_seconds(client_type)
        self.client = OpenAI(
            api_key=api_key,
            base_url=self._normalize_base_url(api_base),
            timeout=timeout_seconds,
        )
        self.model = model
        self.client_type = client_type  # "llm" or "vlm"
        self.model_profile = (model_profile or "general").strip().lower()
        self.timeout_seconds = timeout_seconds

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        response_format: str = None,
    ) -> str:
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            }

            # Use API-level JSON mode for all LLM profiles when a caller requests JSON.
            if response_format == "json":
                kwargs["response_format"] = {"type": "json_object"}

            response = self.client.chat.completions.create(**kwargs)

            # Debug: Check response type
            if isinstance(response, str):
                # Some APIs return string directly
                return response

            # Track token usage
            if hasattr(response, 'usage') and response.usage:
                tracker = get_global_tracker()
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens

                if self.client_type == "vlm":
                    tracker.add_vlm_usage(self.model, prompt_tokens, completion_tokens)
                else:
                    tracker.add_llm_usage(self.model, prompt_tokens, completion_tokens)

            return response.choices[0].message.content
        except AttributeError as e:
            # Handle non-standard API response
            if isinstance(response, str):
                return response
            raise RuntimeError(f"LLM request failed - unexpected response format: {type(response)}, error: {e}")
        except Exception as e:
            raise RuntimeError(f"LLM request failed: {e}")

    def chat_with_image(self, text: str, image_url: str) -> str:
        return self.chat_with_images(text, [image_url])

    def chat_with_images(self, text: str, image_urls: List[str]) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for image_url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": image_url}})

        try:
            messages = [{
                "role": "user",
                "content": content
            }]
            kwargs = {
                "model": self.model,
                "messages": messages,
            }
            response = self.client.chat.completions.create(**kwargs)

            # Debug: Check response type
            if isinstance(response, str):
                # Some APIs return string directly
                return response

            # Track token usage
            if hasattr(response, 'usage') and response.usage:
                tracker = get_global_tracker()
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens

                if self.client_type == "vlm":
                    tracker.add_vlm_usage(self.model, prompt_tokens, completion_tokens)
                else:
                    tracker.add_llm_usage(self.model, prompt_tokens, completion_tokens)

            return response.choices[0].message.content
        except AttributeError as e:
            # Handle non-standard API response
            if isinstance(response, str):
                return response
            raise RuntimeError(f"VLM request failed - unexpected response format: {type(response)}, error: {e}")
        except Exception as e:
            raise RuntimeError(f"VLM request failed: {e}")

    def get_embedding(self, text: str, model: str = "text-embedding-3-small") -> List[float]:
        """Get text embedding using OpenAI embedding API."""
        try:
            response = self.client.embeddings.create(
                model=model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            raise RuntimeError(f"Embedding request failed: {e}")

    @staticmethod
    def _normalize_base_url(api_base: str) -> str:
        """Normalize API base URL by removing trailing slashes.

        Different providers use different version paths:
        - OpenAI: /v1
        - GLM: /api/paas/v4/
        - Qwen: /compatible-mode/v1
        - DeepSeek: /v1

        We don't append /v1 automatically to support all providers.
        """
        return api_base.rstrip("/")

    @staticmethod
    def _resolve_timeout_seconds(client_type: str) -> float:
        if client_type == "vlm":
            candidates = (
                os.getenv("PRESENT_AGENT_VLM_TIMEOUT_SECONDS"),
                os.getenv("PRESENT_AGENT_API_TIMEOUT_SECONDS"),
            )
        else:
            candidates = (
                os.getenv("PRESENT_AGENT_LLM_TIMEOUT_SECONDS"),
                os.getenv("PRESENT_AGENT_API_TIMEOUT_SECONDS"),
            )

        for value in candidates:
            if value is None or value.strip() == "":
                continue
            return float(value)
        return 1800.0
