"""MinerU official API client used by PresentAgent step 1."""

from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


class MinerUClient:
    """Wraps the MinerU official parse APIs for local files and remote URLs."""

    def __init__(
        self,
        api_token: str,
        api_base: str = "https://mineru.net/api/v4",
        model_version: str = "vlm",
        poll_interval: float = 5.0,
        timeout: int = 1800,
        session: requests.Session | None = None,
    ) -> None:
        if not api_token:
            raise ValueError("MinerU API token is required.")

        self.api_token = api_token
        self.api_base = api_base.rstrip("/")
        self.model_version = model_version
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.session = session or requests.Session()

    def parse_pdf(self, source: str, output_dir: str) -> dict[str, Any]:
        """Submit a MinerU parse task, wait for completion, download and extract the result."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        if self._is_url(source):
            task_meta = self._submit_url_task(source)
            result_meta = self._wait_for_task(task_meta["task_id"])
            parse_meta: dict[str, Any] = {
                "source_type": "url",
                "task_id": task_meta["task_id"],
            }
        else:
            file_path = Path(source)
            if not file_path.exists():
                raise FileNotFoundError(f"PDF file not found: {file_path}")
            if file_path.suffix.lower() != ".pdf":
                raise ValueError(f"Expected a PDF file, got: {file_path}")

            batch_meta = self._upload_local_pdf(file_path)
            result_meta = self._wait_for_batch_result(batch_meta["batch_id"], file_path.name)
            parse_meta = {
                "source_type": "file",
                "batch_id": batch_meta["batch_id"],
                "data_id": batch_meta["data_id"],
            }

        full_zip_url = self._extract_full_zip_url(result_meta)
        extract_dir = self._download_and_extract(full_zip_url, output_path)
        parse_meta.update(
            {
                "full_zip_url": full_zip_url,
                "extract_dir": str(extract_dir),
                "result_meta": result_meta,
            }
        )
        return parse_meta

    def _submit_url_task(self, pdf_url: str) -> dict[str, Any]:
        payload = {"url": pdf_url, "model_version": self.model_version}
        data = self._request_json("POST", "/extract/task", json=payload)
        task_id = (
            data.get("task_id")
            or data.get("extract_task_id")
            or data.get("id")
        )
        if not task_id:
            raise RuntimeError(f"MinerU did not return a task id: {data}")
        return {"task_id": task_id}

    def _upload_local_pdf(self, pdf_path: Path) -> dict[str, Any]:
        data_id = pdf_path.stem
        payload = {
            "enable_formula": True,
            "language": "auto",
            "model_version": self.model_version,
            "files": [
                {
                    "name": pdf_path.name,
                    "is_ocr": True,
                    "data_id": data_id,
                }
            ],
        }
        data = self._request_json("POST", "/file-urls/batch", json=payload)
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls") or []

        if not batch_id or not file_urls:
            raise RuntimeError(f"MinerU did not return batch upload metadata: {data}")

        upload_url = self._extract_upload_url(file_urls[0])
        if not upload_url:
            raise RuntimeError(f"MinerU did not return an upload URL: {data}")

        with pdf_path.open("rb") as file_obj:
            response = self.session.put(upload_url, data=file_obj, timeout=300)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Failed to upload PDF to MinerU storage: {response.status_code} {response.text}"
            )

        return {"batch_id": batch_id, "data_id": data_id}

    @staticmethod
    def _extract_upload_url(file_url_entry: Any) -> str:
        if isinstance(file_url_entry, str):
            return file_url_entry
        if isinstance(file_url_entry, dict):
            return str(file_url_entry.get("url") or file_url_entry.get("upload_url") or "")
        return ""

    def _wait_for_task(self, task_id: str) -> dict[str, Any]:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            data = self._request_json("GET", f"/extract/task/{task_id}")
            state = (data.get("state") or data.get("status") or "").lower()
            if state == "done":
                return data.get("extract_result") or data
            if state in {"failed", "error", "canceled", "cancelled"}:
                raise RuntimeError(f"MinerU task {task_id} failed: {data}")
            time.sleep(self.poll_interval)

        raise TimeoutError(f"Timed out waiting for MinerU task {task_id}.")

    def _wait_for_batch_result(self, batch_id: str, file_name: str) -> dict[str, Any]:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            data = self._request_json("GET", f"/extract-results/batch/{batch_id}")
            entries = data.get("extract_result") or data.get("extract_results") or data.get("files") or []
            if not isinstance(entries, list):
                raise RuntimeError(f"Unexpected MinerU batch result shape: {data}")

            for entry in entries:
                entry_name = entry.get("file_name") or entry.get("name")
                if entry_name and entry_name != file_name:
                    continue

                state = (entry.get("state") or entry.get("status") or "").lower()
                if state == "done":
                    return entry
                if state in {"failed", "error", "canceled", "cancelled"}:
                    raise RuntimeError(f"MinerU batch {batch_id} failed for {file_name}: {entry}")

            time.sleep(self.poll_interval)

        raise TimeoutError(f"Timed out waiting for MinerU batch {batch_id}.")

    def _download_and_extract(self, full_zip_url: str, output_dir: Path) -> Path:
        zip_path = output_dir / "mineru_result.zip"
        extract_dir = output_dir / "extracted"

        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        with self.session.get(full_zip_url, stream=True, timeout=300) as response:
            response.raise_for_status()
            with zip_path.open("wb") as file_obj:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file_obj.write(chunk)

        with zipfile.ZipFile(zip_path, "r") as zip_file:
            zip_file.extractall(extract_dir)

        return extract_dir

    def _extract_full_zip_url(self, result_meta: dict[str, Any]) -> str:
        full_zip_url = (
            result_meta.get("full_zip_url")
            or result_meta.get("full_zip_file")
            or result_meta.get("result_zip_url")
        )
        if not full_zip_url:
            raise RuntimeError(f"MinerU result does not include full_zip_url: {result_meta}")
        return full_zip_url

    def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        headers.update(
            {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }
        )
        response = self.session.request(
            method=method,
            url=f"{self.api_base}{path}",
            headers=headers,
            timeout=60,
            **kwargs,
        )
        response.raise_for_status()

        payload = response.json()
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise RuntimeError(f"MinerU API error: {payload}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected MinerU response: {payload}")

        return payload.get("data") or {}

    @staticmethod
    def _is_url(source: str) -> bool:
        parsed = urlparse(source)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
