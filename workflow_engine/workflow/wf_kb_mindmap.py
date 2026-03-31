from __future__ import annotations
import os
import asyncio
from pathlib import Path
from typing import List, Dict, Any

import fitz  # PyMuPDF
from workflow_engine.workflow.registry import register
from workflow_engine.graphbuilder.graph_builder import GenericGraphBuilder
from workflow_engine.logger import get_logger
from workflow_engine.state import KBMindMapState, MainState
from workflow_engine.agentroles import create_agent
from workflow_engine.utils import get_project_root

log = get_logger(__name__)
_mindmap_structure_logged_once = False

# Try importing office libraries
try:
    from docx import Document
except ImportError:
    Document = None

try:
    from pptx import Presentation
except ImportError:
    Presentation = None

@register("kb_mindmap")
def create_kb_mindmap_graph() -> GenericGraphBuilder:
    """
    Workflow for Knowledge Base MindMap Generation
    Steps:
    1. Parse uploaded files (PDF/Office)
    2. Analyze content structure using LLM
    3. Generate Mermaid mindmap syntax using LLM
    """
    builder = GenericGraphBuilder(state_model=KBMindMapState, entry_point="_start_")

    def _extract_text_result(state: MainState, role_name: str) -> str:
        try:
            result = state.agent_results.get(role_name, {}).get("results", {})
            if isinstance(result, dict):
                return result.get("text") or result.get("raw") or ""
            if isinstance(result, str):
                return result
        except Exception:
            return ""
        return ""

    def _start_(state: KBMindMapState) -> KBMindMapState:
        # Ensure request fields
        if not state.request.file_ids:
            state.request.file_ids = []

        # Initialize output directory
        if not state.result_path:
            project_root = get_project_root()
            import time
            ts = int(time.time())
            email = getattr(state.request, 'email', 'default')
            output_dir = project_root / "outputs" / "kb_outputs" / email / f"{ts}_mindmap"
            output_dir.mkdir(parents=True, exist_ok=True)
            state.result_path = str(output_dir)

        state.file_contents = []
        state.content_structure = ""
        state.mermaid_code = ""
        state.mindmap_svg_path = ""
        return state

    async def parse_files_node(state: KBMindMapState) -> KBMindMapState:
        """
        Parse all files and extract content
        """
        files = state.request.file_ids
        if not files:
            state.file_contents = []
            return state

        async def process_file(file_path: str) -> Dict[str, Any]:
            file_path_obj = Path(file_path)
            filename = file_path_obj.name

            if not file_path_obj.exists():
                return {
                    "filename": filename,
                    "content": f"[Error: File not found {file_path}]"
                }

            suffix = file_path_obj.suffix.lower()
            raw_content = ""

            try:
                # PDF
                if suffix == ".pdf":
                    try:
                        doc = fitz.open(file_path)
                        text = ""
                        for page in doc:
                            text += page.get_text() + "\n"
                        raw_content = text
                    except Exception as e:
                        raw_content = f"[Error parsing PDF: {e}]"

                # Word
                elif suffix in [".docx", ".doc"]:
                    if Document is None:
                         raw_content = "[Error: python-docx not installed]"
                    else:
                        try:
                            doc = Document(file_path)
                            raw_content = "\n".join([p.text for p in doc.paragraphs])
                        except Exception as e:
                             raw_content = f"[Error parsing Docx: {e}]"

                # PPT
                elif suffix in [".pptx", ".ppt"]:
                    if Presentation is None:
                        raw_content = "[Error: python-pptx not installed]"
                    else:
                        try:
                            prs = Presentation(file_path)
                            text = ""
                            for i, slide in enumerate(prs.slides):
                                text += f"--- Slide {i+1} ---\n"
                                for shape in slide.shapes:
                                    if hasattr(shape, "text"):
                                        text += shape.text + "\n"
                            raw_content = text
                        except Exception as e:
                            raw_content = f"[Error parsing PPT: {e}]"

                else:
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            raw_content = f.read()
                    except:
                        raw_content = "[Unsupported file type]"

            except Exception as e:
                 raw_content = f"[Parse Error: {e}]"

            # Truncate content
            truncated_content = raw_content[:50000] if len(raw_content) > 50000 else raw_content

            return {
                "filename": filename,
                "content": truncated_content
            }

        # Run in parallel
        tasks = [process_file(f) for f in files]
        results = await asyncio.gather(*tasks)

        state.file_contents = results
        return state

    async def analyze_structure_node(state: KBMindMapState) -> KBMindMapState:
        """Skip — merged into generate_mermaid_node for single-pass generation."""
        state.content_structure = "merged"
        return state

    async def generate_mermaid_node(state: KBMindMapState) -> KBMindMapState:
        """
        Single-pass: analyze documents and generate Markdown mindmap directly.
        """
        if not state.file_contents:
            state.mermaid_code = "# Error\n## No content available"
            return state

        contents_str = ""
        for item in state.file_contents:
            contents_str += f"=== {item['filename']} ===\n{item['content']}\n\n"

        language = state.request.language
        max_depth = state.request.max_depth

        prompt = f"""请基于以下文档内容，生成一张层级清晰、主题归纳明确、适合快速把握全文结构的思维导图。你的目标是把文章压缩成一张"知识地图"，让读者能够迅速理解这篇文章的核心主题、主要模块、关键内容，以及各部分之间的层级关系。

请按照下面的方法完成：

先通读全文，识别文章真正的中心主题，用一句高度概括的话作为根节点。这个根节点需要能够覆盖全文主旨，而不是局部内容。输出时将根节点作为**一级标题（#）**呈现。

然后围绕中心主题，提炼出最能代表全文结构的主分支，优先控制在 4–8 个范围内，并将它们作为**二级标题（##）**呈现。主分支要能够代表全文最重要的几个结构板块。请优先从文章本身的结构、论述重心、主题模块、关键信息簇中提炼主分支，使它们能够共同构成全文的主干。

接着在每个主分支下继续拆分 2–4 个子主题，并将它们作为**三级标题（###）**呈现。子主题要承接上级主题，概括该部分最值得保留的核心内容，例如关键概念、主要论点、重要机制、核心步骤、代表性案例、主要证据、结果表现、应用场景、影响因素、行动建议等。

需要时继续向下拆分更细的层级，整体层级最多{max_depth}层（使用 # 到 {'#' * max_depth} 表示）。请根据内容复杂度自然决定展开深度，使层级既完整又紧凑。使用{language}语言。

整张思维导图要体现出一种知识整理型、结构概览型、主题分解型的风格。重点是帮助读者快速理解全文内容版图，而不是只罗列摘要句子。请让结构体现出"从总到分、由主到次、层层展开"的组织逻辑。

请根据文章类型，自适应选择最合适的组织框架：

研究型、分析型文章：背景、问题、核心观点、方法机制、证据结果、意义影响、局限延伸
新闻、时评、纪实型文章：主题事件、背景脉络、关键事实、各方观点、原因影响、趋势走向
科普、说明型文章：核心概念、原理机制、特征表现、应用场景、常见理解、总结启发
教程、方法型文章：目标、前提条件、步骤模块、关键技巧、注意事项、应用建议
商业、产品、行业文章：对象定位、背景环境、核心策略、运行方式、优势价值、风险挑战、发展趋势
访谈、观点型文章：核心立场、主要观点、支撑理由、经验案例、延伸启示

节点命名请尽量简洁而有信息量。每个节点都使用适合放入思维导图框中的短语式表达，让人一眼就能理解该节点要表达的重点。

请将语义接近、作用相同、共同服务于同一主题的信息归并到同一分支下，形成稳定的主题模块。请优先把能够解释全文结构的内容放在上层节点，把例子、数据、条件、补充说明放在下层节点。

特别注意：如果原文包含关键数据、时间、比例、数量、金额、指标或实验结果，请在相关节点中保留这些具体信息。在涉及结果、变化、比较、规模、金额、比例、时间、指标和实验表现时，请优先使用原文中的具体数字和定量信息来命名或补充节点内容。

生成标准：

1. 忠实反映原文主线，保留关键数据和定量结果
2. 节点之间要有明确层级关系
3. 同一级节点尽量保持并列、均衡、可比较
4. 优先保留能够帮助理解全文框架的内容
5. 让整张图看起来像一张"文章结构与知识重点总览图"
6. 读者即使不读原文，也能通过这张导图把握文章的大体结构与核心内容

输出格式要求：

1. 使用 Markdown 标题格式：# 根节点，## 主分支，### 子主题，#### 及以下为进一步展开层级
2. 最终结果直接以 Markdown 主体输出，内容从根节点开始展开
3. 采用纯 Markdown 标题结构呈现结果

文档内容：
{contents_str}

请严格按照文档内容前的要求来完成，特别注意：
1. 采用纯 Markdown 标题结构（# ## ### ####），不要使用代码块或其他格式
2. 保留原文中的关键数据、数字和定量信息
3. 节点简洁有信息量，用短语式表达而非长句
4. 层级清晰，从总到分、由主到次
5. 不要输出任何解释或额外文字，直接从根节点开始输出："""

        try:
            agent = create_agent(
                name="kb_prompt_agent",
                model_name=state.request.model,
                chat_api_url=state.request.chat_api_url,
                temperature=0.3,
                parser_type="text"
            )

            temp_state = MainState(request=state.request)
            res_state = await agent.execute(temp_state, prompt=prompt)

            mermaid_raw = _extract_text_result(res_state, "kb_prompt_agent")
            if mermaid_raw:
                # Extract content from markdown code blocks if present
                if "```" in mermaid_raw:
                    lines = mermaid_raw.split("\n")
                    in_code_block = False
                    code_lines = []
                    for line in lines:
                        if line.strip().startswith("```"):
                            in_code_block = not in_code_block
                            continue
                        if in_code_block:
                            code_lines.append(line)
                    state.mermaid_code = "\n".join(code_lines)
                else:
                    state.mermaid_code = mermaid_raw
            else:
                state.mermaid_code = "# Error\n## Generation failed"
        except Exception as e:
            log.error(f"Mindmap generation failed: {e}")
            state.mermaid_code = f"# Error\n## {str(e)}"

        # Save mermaid code to file
        try:
            mermaid_path = Path(state.result_path) / "mindmap.mmd"
            mermaid_path.write_text(state.mermaid_code, encoding="utf-8")
            log.info(f"Mermaid code saved to: {mermaid_path}")
        except Exception as e:
            log.error(f"Failed to save mermaid code: {e}")

        return state

    nodes = {
        "_start_": _start_,
        "parse_files": parse_files_node,
        "analyze_structure": analyze_structure_node,
        "generate_mermaid": generate_mermaid_node,
        "_end_": lambda s: s
    }

    edges = [
        ("_start_", "parse_files"),
        ("parse_files", "analyze_structure"),
        ("analyze_structure", "generate_mermaid"),
        ("generate_mermaid", "_end_")
    ]

    builder.add_nodes(nodes).add_edges(edges)
    return builder
