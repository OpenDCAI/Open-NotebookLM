"""
Data Insight Service
Handles file upload and calls adapter.
"""
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import UploadFile

from workflow_engine.logger import get_logger
from workflow_engine.utils import get_project_root
from fastapi_app.workflow_adapters.wa_data_insight import DataInsightAdapter

log = get_logger(__name__)


class DataInsightService:
    """Data insight analysis service"""

    def _create_upload_dir(self, email: Optional[str]) -> Path:
        """Create directory for uploaded files."""
        ts = int(time.time())
        root = get_project_root()
        upload_dir = root / "outputs" / "data_insights" / (email or "default") / f"{ts}_upload"
        upload_dir.mkdir(parents=True, exist_ok=True)
        return upload_dir

    async def analyze_datasets(
        self,
        chat_api_url: str,
        api_key: str,
        model: str,
        output_mode: str,
        analysis_goal: Optional[str],
        language: str,
        email: Optional[str],
        files: List[UploadFile],
    ) -> Dict[str, Any]:
        """
        Execute insight analysis workflow.

        Args:
            chat_api_url: LLM API URL
            api_key: LLM API key
            model: Model name
            output_mode: "concise" or "detailed"
            analysis_goal: Optional custom goal
            language: Language preference
            email: User email
            files: Uploaded data files

        Returns:
            Analysis results dict
        """
        # Save uploaded files
        upload_dir = self._create_upload_dir(email)
        file_paths = []

        for file in files:
            file_path = upload_dir / (file.filename or f"file_{len(file_paths)}.csv")
            content = await file.read()
            file_path.write_bytes(content)
            file_paths.append(str(file_path))
            log.info(f"Uploaded: {file.filename}")

        # Build request dict
        request_data = {
            "file_ids": file_paths,
            "model": model,
            "api_key": api_key,
            "chat_api_url": chat_api_url,
            "output_mode": output_mode,
            "analysis_goal": analysis_goal,
            "language": language,
            "email": email
        }

        # Call adapter (NOT workflow directly)
        adapter = DataInsightAdapter()
        result = await adapter.execute(request_data)

        return result
