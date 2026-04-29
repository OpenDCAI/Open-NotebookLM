from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi_app.services.conversation_workspace_service import ConversationWorkspaceService
from fastapi_app.services.document_service import DocumentService
from workflow_engine.utils import get_project_root


class ThinkFlowChatContextService:
    """Build the 0426 workspace chat context in one backend-owned place."""

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.project_root = Path(project_root) if project_root is not None else get_project_root()
        self.conversations = ConversationWorkspaceService(project_root=self.project_root)
        self.documents = DocumentService(project_root=self.project_root)

    def _truncate(self, text: str, max_chars: int) -> str:
        value = str(text or "")
        if len(value) <= max_chars:
            return value
        return f"{value[:max_chars].rstrip()}\n\n...[已截断]"

    def _format_source_refs(self, refs: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for index, ref in enumerate(refs, start=1):
            title = str(ref.get("title") or ref.get("id") or "未命名来源").strip()
            source_type = str(ref.get("type") or "material").strip()
            path = str(ref.get("path") or "").strip()
            suffix = f" ({path})" if path else ""
            lines.append(f"- 来源 {index}: [{source_type}] {title}{suffix}")
        return "\n".join(lines)

    def _format_reference_documents(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        refs: List[Dict[str, Any]],
    ) -> str:
        blocks: List[str] = []
        document_refs = [
            ref for ref in refs
            if str(ref.get("type") or "").strip() in {"document", "output_document"} and str(ref.get("id") or "").strip()
        ]
        for index, ref in enumerate(document_refs, start=1):
            document_id = str(ref.get("id") or "").strip()
            fallback_title = str(ref.get("title") or document_id or "未命名文档").strip()
            try:
                document = self.documents.get_document(
                    notebook_id=notebook_id,
                    notebook_title=notebook_title,
                    user_id=user_id,
                    document_id=document_id,
                )
            except Exception:
                blocks.append(
                    "\n".join(
                        [
                            f"[参考文档 {index}]",
                            f"标题：{fallback_title}",
                            "参考范围：文档不可用",
                        ]
                    )
                )
                continue

            title = str(document.get("title") or fallback_title or "未命名文档").strip()
            content = str(document.get("content") or "")
            focus_state = document.get("focus_state") or {}
            focus_type = str(focus_state.get("type") or "full").strip()
            section_ids = [
                str(item or "").strip()
                for item in (focus_state.get("section_ids") if isinstance(focus_state.get("section_ids"), list) else [])
                if str(item or "").strip()
            ]
            selected_sections: List[Dict[str, Any]] = []
            if focus_type == "sections" and section_ids:
                parsed_sections = self.documents._parse_markdown_sections(
                    content,
                    document_type=str(document.get("document_type") or "summary_doc"),
                )
                selected_sections = [section for section in parsed_sections if str(section.get("id") or "") in section_ids]

            if selected_sections:
                headings = [str(section.get("heading") or "未命名模块").strip() for section in selected_sections]
                module_text = "\n\n".join(str(section.get("text") or "").strip() for section in selected_sections if str(section.get("text") or "").strip())
                blocks.append(
                    "\n".join(
                        [
                            f"[参考文档 {index}]",
                            f"标题：{title}",
                            "参考范围：选中模块",
                            f"选中模块：{' / '.join(headings)}",
                            "模块内容：",
                            self._truncate(module_text, 8000),
                        ]
                    )
                )
            else:
                blocks.append(
                    "\n".join(
                        [
                            f"[参考文档 {index}]",
                            f"标题：{title}",
                            "参考范围：全文",
                            "文档内容：",
                            self._truncate(content, 8000),
                        ]
                    )
                )
        return "\n\n".join(block for block in blocks if block.strip())

    def build_context(
        self,
        *,
        notebook_id: str,
        notebook_title: str,
        user_id: str,
        conversation_id: str,
        user_message: str,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        conversation_state = self.conversations.get_state(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        active_document_id = str(conversation_state.get("active_document_id") or "").strip()
        sections: List[str] = [
            "[系统提示词]",
            "你是 ThinkFlow 工作区里的 AI。文档只能通过用户显式推送动作被修改；普通聊天只回答问题。",
        ]

        source_refs = conversation_state.get("source_refs") or []
        reference_documents_text = self._format_reference_documents(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            user_id=user_id,
            refs=source_refs,
        )
        if reference_documents_text:
            sections.append(reference_documents_text)

        source_text = self._format_source_refs(source_refs)
        if source_text:
            sections.extend(["[对话来源]", source_text])

        sections.extend(["[用户新消息]", str(user_message or "").strip()])
        context_text = "\n\n".join(section for section in sections if str(section or "").strip())
        return {
            "conversation_id": conversation_id,
            "active_document_id": active_document_id,
            "source_refs": conversation_state.get("source_refs") or [],
            "context_text": context_text,
            "rag_query": str(user_message or "").strip(),
        }
