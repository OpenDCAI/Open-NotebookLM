"""
Data Insight Discovery API
Multi-dataset insight analysis using DM framework.
"""
import json
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

import pandas as pd

from workflow_engine.logger import get_logger
from fastapi_app.services.data_insight_service import DataInsightService

log = get_logger(__name__)
router = APIRouter(prefix="/data_insight", tags=["data_insight"])


# ==================== Pydantic Models ====================
class DataInsightResponse(BaseModel):
    """Response model for data insight analysis"""
    status: str
    synthesized_insights: List[str]
    raw_insights: List[str]
    summary: str
    detailed_appendix: Dict[str, Any] = {}
    result_path: str = ""
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    code: str = "INTERNAL_ERROR"
    details: Optional[Dict] = None


# ==================== API Endpoints ====================
@router.post(
    "/analyze",
    response_model=DataInsightResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def analyze_datasets(
    chat_api_url: str = Form(..., description="LLM API URL"),
    api_key: str = Form(..., description="LLM API key"),
    model: str = Form("deepseek-v3.2", description="Model name"),
    output_mode: str = Form("concise", description="Output mode: concise or detailed"),
    language: str = Form("en", description="Language preference"),
    files: List[UploadFile] = File(..., description="Data files (CSV, Excel)"),
    analysis_goal: Optional[str] = Form(None, description="Custom analysis goal"),
    email: Optional[str] = Form(None, description="User email"),
):
    """
    Analyze multiple datasets and discover insights.

    Accepts CSV, Excel files.
    Returns synthesized insights and summary.
    """
    try:
        # Validate inputs
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        if not api_key or not chat_api_url:
            raise HTTPException(status_code=400, detail="API key and URL required")

        # Call service
        service = DataInsightService()
        result = await service.analyze_datasets(
            chat_api_url=chat_api_url,
            api_key=api_key,
            model=model,
            output_mode=output_mode,
            analysis_goal=analysis_goal,
            language=language,
            email=email,
            files=files,
        )

        # Check for errors
        if result.get("status") == "error":
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Analysis failed")
            )

        # Convert raw_insights from dict to string if needed
        raw_insights = result.get("raw_insights", [])
        if raw_insights and isinstance(raw_insights[0], dict):
            # Convert dict format to string representation
            result["raw_insights"] = [
                f"[{item.get('source', 'unknown')}] {item.get('insight', str(item))}"
                for item in raw_insights
            ]

        return DataInsightResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Unexpected error in analyze_datasets: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Helper Functions ====================
def generate_markdown_report(
    synthesized_insights: List[str],
    raw_insights: List[str],
    summary: str,
    detailed_appendix: Dict[str, Any],
    language: str = "en"
) -> str:
    """
    Generate a markdown report from analysis results.

    Args:
        synthesized_insights: List of synthesized insights
        raw_insights: List of raw insights from individual agents
        summary: Overall summary
        detailed_appendix: Detailed appendix data
        language: Language preference (en/zh)

    Returns:
        Markdown formatted report content
    """
    lang = language.lower()
    is_zh = lang == "zh"

    # Headers
    title = "📊 Data Insight Report" if is_zh else "📊 Data Insight Report"
    summary_header = "📝 Summary" if is_zh else "📝 Summary"
    insights_header = "💡 Key Insights" if is_zh else "💡 Key Insights"
    raw_header = "📋 Raw Analysis" if is_zh else "📋 Raw Analysis"
    appendix_header = "📎 Detailed Appendix" if is_zh else "📎 Detailed Appendix"
    footer = f"*Generated on {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*" if is_zh else f"*Generated on {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*"

    # Build report
    report_lines = [
        f"# {title}",
        "",
        f"## {summary_header}",
        "",
        summary,
        "",
        f"## {insights_header}",
        ""
    ]

    # Add synthesized insights
    for i, insight in enumerate(synthesized_insights, 1):
        if is_zh:
            report_lines.append(f"### Insight {i}")
        else:
            report_lines.append(f"### Insight {i}")
        report_lines.append("")
        report_lines.append(insight)
        report_lines.append("")

    # Add raw insights if available
    if raw_insights:
        report_lines.append(f"## {raw_header}")
        report_lines.append("")
        for i, insight in enumerate(raw_insights, 1):
            report_lines.append(f"**{i}.** {insight}")
            report_lines.append("")

    # Add detailed appendix if available
    if detailed_appendix:
        report_lines.append(f"## {appendix_header}")
        report_lines.append("")
        for key, value in detailed_appendix.items():
            report_lines.append(f"### {key}")
            report_lines.append("")
            if isinstance(value, dict):
                for k, v in value.items():
                    report_lines.append(f"- **{k}:** {v}")
            elif isinstance(value, list):
                for item in value:
                    report_lines.append(f"- {item}")
            else:
                report_lines.append(str(value))
            report_lines.append("")

    # Add footer
    report_lines.append("---")
    report_lines.append("")
    report_lines.append(footer)

    return "\n".join(report_lines)


# ==================== New API Endpoints ====================
@router.post(
    "/generate_report",
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def generate_report(
    synthesized_insights: str = Form(..., description="JSON string of synthesized insights"),
    raw_insights: str = Form(..., description="JSON string of raw insights"),
    summary: str = Form(..., description="Analysis summary"),
    detailed_appendix: str = Form("{}", description="JSON string of detailed appendix"),
    language: str = Form("en", description="Language preference"),
):
    """
    Generate a markdown report from analysis results.
    """
    try:
        # Parse JSON strings
        synthesized = json.loads(synthesized_insights) if synthesized_insights else []
        raw = json.loads(raw_insights) if raw_insights else []
        appendix = json.loads(detailed_appendix) if detailed_appendix else {}

        # Generate markdown report
        report_content = generate_markdown_report(
            synthesized_insights=synthesized,
            raw_insights=raw,
            summary=summary,
            detailed_appendix=appendix,
            language=language
        )

        # Save to temporary file
        temp_dir = Path(tempfile.gettempdir()) / "data_insight_reports"
        temp_dir.mkdir(parents=True, exist_ok=True)

        report_filename = f"insight_report_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path = temp_dir / report_filename
        report_path.write_text(report_content, encoding='utf-8')

        log.info(f"Generated markdown report: {report_path}")

        return FileResponse(
            path=str(report_path),
            filename=report_filename,
            media_type='text/markdown'
        )

    except json.JSONDecodeError as e:
        log.error(f"JSON decode error: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON format in request")
    except Exception as e:
        log.error(f"Error generating report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
