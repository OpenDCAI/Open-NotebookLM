"""Table Processing Workflow - Self-contained workflow using workflow_engine components.

This workflow implements the full table processing pipeline:
1. intent_understanding: Parse user intent into task type and operation
2. data_profiling: Profile the input tables
3. decompositer: Decompose complex tasks (optional)
4. generator: Generate Python code for the task
5. evaluator: Execute and validate the generated code
6. debugger: Debug failed code (if needed)
7. summarizer: Summarize results

The workflow uses workflow_engine's agent system and tools instead of table_agent.
"""
from __future__ import annotations

import json
import os
import shutil
import traceback
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, AIMessage

from workflow_engine.graphbuilder.graph_builder import GenericGraphBuilder
from workflow_engine.state import TableProcessingState
from workflow_engine.workflow.registry import register
from workflow_engine.agentroles import create_simple_agent
from workflow_engine.logger import get_logger
from workflow_engine.constants import (
    MAX_REACT_STEPS,
    MAX_GENERATE_ATTEMPTS,
    MAX_DEBUG_ATTEMPTS,
    BENCHMARK_TASK_TYPES,
)
from workflow_engine.table_agent_utils import (
    get_paths,
    safe_exec_code,
    extract_python_code_block,
    write_code_file,
    write_eval_result,
    profile_multiple_csvs,
    parse_react_output,
    observation_to_message,
    truncate_for_log,
)

# 导入自定义策略以触发自动注册，并获取 create_table_react_agent 函数
from workflow_engine.workflow.wf_table_strategy import create_table_react_agent

log = get_logger(__name__)

CURRENT_DIR = Path(__file__).parent.parent.resolve()


@register("table_processing_workflow")
def create_table_processing_workflow() -> GenericGraphBuilder:
    """Create the table processing workflow graph."""
    builder = GenericGraphBuilder(
        state_model=TableProcessingState,
        entry_point="intent_understanding"
    )

    # =======================================================================
    # Pre-tools for each node
    # =======================================================================

    @builder.pre_tool("user_input", "intent_understanding")
    def _user_input(state: TableProcessingState):
        return state.get("task_objective", "")

    @builder.pre_tool("task_meta", "intent_understanding")
    def _task_meta(state: TableProcessingState):
        return state.get("data_profiling", {})

    # -----------------------------------------------------------------------
    # Data profiling pre-tools
    @builder.pre_tool("raw_table_paths", "data_profiling")
    def _raw_table_paths(state: TableProcessingState):
        return state.get("raw_table_paths", [])

    @builder.pre_tool("operation", "data_profiling")
    def _operation(state: TableProcessingState):
        user_query = state.get("user_query", {})
        if isinstance(user_query, dict):
            return user_query.get("operation", "")
        return ""

    @builder.pre_tool("MAX_REACT_STEPS", "data_profiling")
    def _max_react_steps(state: TableProcessingState):
        return MAX_REACT_STEPS

    @builder.pre_tool("user_refine_input", "data_profiling")
    def _user_refine_input(state: TableProcessingState):
        score = state.get("score", 0.0)
        score_rule = state.get("score_rule", "")
        profiling_trace_summary = state.get("profiling_trace_summary", "")
        insight = state.get("summary", "")
        return f"""
        Based on the previous profiling trace summary: {profiling_trace_summary},
        Based on the previous insight(about why agent don't do well): {insight}, try your best to improve quality of the profiling.
        """

    # -----------------------------------------------------------------------
    # Decompositer pre-tools
    @builder.pre_tool("user_query", "decompositer")
    def _decompositer_user_query(state: TableProcessingState):
        user_query = state.get("user_query", {})
        if isinstance(user_query, dict):
            return json.dumps(user_query, ensure_ascii=False)
        return str(user_query)

    @builder.pre_tool("benchmark_task_types", "decompositer")
    def _benchmark_task_types(state: TableProcessingState):
        return json.dumps(BENCHMARK_TASK_TYPES, ensure_ascii=False)

    # -----------------------------------------------------------------------
    # Generator pre-tools
    @builder.pre_tool("task_meta", "generator")
    def _generator_task_meta(state: TableProcessingState):
        return state.get("data_profiling", {})

    @builder.pre_tool("user_query", "generator")
    def _generator_user_query(state: TableProcessingState):
        user_query = state.get("user_query", {})
        if isinstance(user_query, dict):
            return json.dumps(user_query, ensure_ascii=False)
        return str(user_query)

    @builder.pre_tool("user_input", "generator")
    def _generator_user_input(state: TableProcessingState):
        user_inputs = [state.get("task_objective", "")]
        input_paths = " ".join(Path(p).name for p in state.get("raw_table_paths", []))
        user_inputs.append(f"输入文件的顺序与类型：{input_paths}")
        if state.get("debug_reasons"):
            user_inputs.append(
                f"Debug Reasons:{state['debug_reasons']} You need to avoid the previous mistakes."
            )
        if state.get("summary"):
            user_inputs.append(f"Additional Context: {state.get('summary')}")
        return user_inputs

    @builder.pre_tool("retrieved_operators", "generator")
    def _retrieved_operators(state: TableProcessingState):
        return state.get("retrieved_operators", [])

    # -----------------------------------------------------------------------
    # Debugger pre-tools
    @builder.pre_tool("code", "debugger")
    def _code(state: TableProcessingState):
        previews_generated_codes = state.get("generated_codes", [])
        return previews_generated_codes[-1] if previews_generated_codes else ""

    @builder.pre_tool("error", "debugger")
    def _error(state: TableProcessingState):
        error_logs = state.get("error_logs", [])
        return error_logs[-1] if error_logs else ""

    @builder.pre_tool("target", "debugger")
    def _target(state: TableProcessingState):
        user_query = state.get("user_query", {})
        if isinstance(user_query, dict):
            return user_query.get("operation", "")
        return ""

    @builder.pre_tool("input_file_paths", "debugger")
    def _input_file_paths(state: TableProcessingState):
        return " ".join(Path(p).name for p in state.get("raw_table_paths", []))

    @builder.pre_tool("debug_history", "debugger")
    def _debug_history(state: TableProcessingState):
        error_logs = state.get("error_logs", [])
        return error_logs[:-1] if len(error_logs) > 1 else "No previous debug history."

    # -----------------------------------------------------------------------
    # Summarizer pre-tools
    @builder.pre_tool("processed_file_paths", "summarizer")
    def _processed_file_paths(state: TableProcessingState):
        return state.get("processed_file_paths", [])

    @builder.pre_tool("task_objective", "summarizer")
    def _task_objective(state: TableProcessingState):
        return state.get("task_objective", "")

    @builder.pre_tool("raw_file_paths", "summarizer")
    def _raw_file_paths(state: TableProcessingState):
        return state.get("raw_table_paths", [])

    @builder.pre_tool("score", "summarizer")
    def _score(state: TableProcessingState):
        return state.get("score", 0.0)

    @builder.pre_tool("score_rule", "summarizer")
    def _score_rule(state: TableProcessingState):
        return state.get("score_rule", "")

    @builder.pre_tool("summarizing_trace_summary", "summarizer")
    def _summarizing_trace_summary(state: TableProcessingState):
        return state.get("summarizing_trace_summary", "")

    @builder.pre_tool("task_meta", "summarizer")
    def _summarizer_task_meta(state: TableProcessingState):
        return state.get("data_profiling", {})

    @builder.pre_tool("MAX_REACT_STEPS", "summarizer")
    def _summarizer_max_react_steps(state: TableProcessingState):
        return MAX_REACT_STEPS

    # =======================================================================
    # Node implementations
    # =======================================================================

    async def intent_understanding(state: TableProcessingState) -> TableProcessingState:
        """Parse user intent into task type and operation."""
        log.info("🔍 开始意图识别...")
        model = state.request.model or state.get("model", "deepseek-v3.2")

        agent = create_simple_agent(
            name="intent_understanding",
            model_name=model,
            temperature=0.3,
            max_tokens=20480,
            parser_type="json",
        )

        state = await agent.execute(state=state)
        agent_result = state.agent_results.get("intent_understanding", {})
        user_query = agent_result.get("results", {})

        if isinstance(user_query, dict):
            required = {"operation", "reason", "task_type", "suffix"}
            if not required.issubset(user_query.keys()):
                raise ValueError(f"Missing required fields in intent_understanding result: {required - set(user_query.keys())}")

        state["user_query"] = user_query
        state["task_type"] = user_query.get("task_type", "TableCleaning-DataImputation")
        log.info(f"✅ 意图解析成功: {user_query}")
        return state

    async def data_profiling(state: TableProcessingState) -> TableProcessingState:
        """Profile the input tables using TableReAct Strategy."""
        log.info("📊 开始数据画像...")
        model = state.request.model or state.get("model", "deepseek-v3.2")

        agent = create_table_react_agent(
            name="data_profiling",
            model_name=model,
            max_retries=MAX_REACT_STEPS,
            parser_type="json",
        )

        state = await agent.execute(state=state)
        agent_result = state.agent_results.get("data_profiling", {})
        results = agent_result.get("results", {})
        data_profiling = results.get("answer", {})
        react_trace = results.get("react_trace", [])

        log.info(f"📊 Profiling 原始输出：{data_profiling}")

        if state.get("llm_tracker"):
            summary_messages = [
                {"role": "system", "content": "Summarize the following ReAct trace briefly."},
                {"role": "user", "content": f"ReAct Trace: {json.dumps(react_trace, ensure_ascii=False)}"},
            ]
            local_summarizer_response = await state["llm_tracker"](summary_messages)
            profiling_trace_summary = local_summarizer_response.content.strip()
            log.info(f"📊 Local Summarizer ReAct Trace Summary:\n{profiling_trace_summary}")
        else:
            profiling_trace_summary = ""

        if "error" not in data_profiling:
            state["data_profiling"] = data_profiling
        else:
            log.warning("📊 Profiling 返回 error，保留原有的 state.data_profiling")

        state["profiling_trace_summary"] = profiling_trace_summary
        state["execution_time"] = results.get("execution_time", 0.0)
        return state

    async def decompositer(state: TableProcessingState) -> TableProcessingState:
        """Decompose complex tasks into sub-tasks."""
        log.info("🔄 开始任务分解...")
        model = state.request.model or state.get("model", "deepseek-v3.2")

        agent = create_simple_agent(
            name="decompositer",
            model_name=model,
            temperature=0.1,
            max_tokens=20480,
            parser_type="text",
        )

        state = await agent.execute(state=state)
        agent_result = state.agent_results.get("decompositer", {})
        decomposition_result = agent_result.get("results", {})

        if isinstance(decomposition_result, dict):
            decomposition_result = json.dumps(decomposition_result, ensure_ascii=False)
        elif not isinstance(decomposition_result, str):
            decomposition_result = str(decomposition_result)

        log.info(f"Decompositer 原始输出：{decomposition_result}")

        try:
            parsed_result = json.loads(decomposition_result)
            for sub_task, task_desc in parsed_result.items():
                log.info(f"子任务: {sub_task} 描述: {task_desc}")
        except json.JSONDecodeError:
            log.warning(f"Decompositer output is not valid JSON: {decomposition_result}")
            parsed_result = {}

        state["decomposition_result"] = decomposition_result
        state["retrieved_operators"] = []
        return state

    async def generator(state: TableProcessingState) -> TableProcessingState:
        """Generate Python code for the task using TableReAct Strategy."""
        log.info("🛠️ 开始代码生成...")
        model = state.request.model or state.get("model", "deepseek-v3.2")

        agent = create_simple_agent(
            name="generator",
            model_name=model,
            parser_type="text",
            temperature=0.1,
            max_tokens=20480,
        )

        state = await agent.execute(state=state)

        code = extract_python_code_block(state["agent_results"]["generator"]["results"]['text'])
        code_path = write_code_file(state.get("result_path", ""), code)

        attempts = state.get("attempts", 0) + 1
        generated_codes = state.get("generated_codes", []) + [code]

        log.info(f"GenerationStrategy 生成代码 (尝试 {attempts})")
        log.info(f"代码已写入: {code_path}")

        state["generated_codes"] = generated_codes
        state["attempts"] = attempts
        return state

    async def evaluator(state: TableProcessingState) -> TableProcessingState:
        """Execute and validate the generated code."""
        log.info("🧪 开始执行与评估...")
        execution_time = state.get("execution_time", 0.0)
        script_generated_total = state.get("script_generated_total", 0) + 1
        script_runnable_total = state.get("script_runnable_total", 0)

        try:
            code_path, process_table_path = get_paths(state.get("result_path", ""))
            log.info(f"Raw table paths: {state['raw_table_paths']}")

            stdout, exec_time = safe_exec_code(
                code_path,
                process_table_path,
                state.get("raw_table_paths", [])
            )
            execution_time += exec_time

            processed_files = [str(f) for f in Path(process_table_path).iterdir() if f.is_file()]
            log.info(f"✅ 评估成功 | Processed files: {processed_files} | Execution time: {execution_time:.2f}s")

            feedback = {"status": "success", "reason": "Execution succeeded."}
            script_runnable_total += 1

            return {
                "messages": [AIMessage(content=f"[Evaluator] feedback={feedback}")],
                "valid": True,
                "evaluation_feedbacks": state.get("evaluation_feedbacks", []) + [feedback],
                "execution_time": execution_time,
                "script_generated_total": script_generated_total,
                "script_runnable_total": script_runnable_total,
                "processed_file_paths": processed_files,
            }
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"[Evaluator] 执行失败: {e}\n{tb}"
            log.error(f"💥 执行失败 | Error: {e}")
            feedback = {"score": 0.0, "status": "error", "reason": str(e), "traceback": tb}

            return {
                "messages": [AIMessage(content="Error:" + error_msg)],
                "valid": False,
                "error_logs": state.get("error_logs", []) + [error_msg],
                "evaluation_feedbacks": state.get("evaluation_feedbacks", []) + [feedback],
                "execution_time": execution_time,
                "script_generated_total": script_generated_total,
            }

    async def debugger(state: TableProcessingState) -> TableProcessingState:
        """Debug failed code."""
        log.info("🐞 开始调试代码...")
        code = ""
        reason = ""
        model = state.request.model or state.get("model", "deepseek-v3.2")

        agent = create_simple_agent(
            name="debugger",
            model_name=model,
            temperature=0.1,
            max_tokens=20480,
            parser_type="json",
        )

        for attempt in range(MAX_DEBUG_ATTEMPTS):
            state = await agent.execute(state=state)
            agent_result = state.agent_results.get("debugger", {})
            last_raw = str(agent_result.get("results", {}))

            try:
                if isinstance(agent_result.get("results"), dict):
                    parsed = agent_result["results"]
                else:
                    parsed = json.loads(last_raw)
                code = parsed.get("code", "")
                reason = parsed.get("reason", "")
            except json.JSONDecodeError:
                log.warning(f"调试 JSON 解析失败: {attempt + 1}")
                continue

            if code:
                break

        if not code:
            eval_result_path = os.path.join(state.get("result_path", ""), "eval_result.txt")
            with open(eval_result_path, "w", encoding="utf-8") as f:
                f.write("Score: 0.0\nValid: False\nError: Debugger 未能生成有效代码（多次失败）。\n")
            raise ValueError("Debugger 未能生成有效代码（多次失败）。")

        code_path = write_code_file(state.get("result_path", ""), code)
        log.info(f"Debugger 生成调试后代码: {code_path}")

        debug_attempts = state.get("debug_attempts", 0) + 1
        debug_total_attempts = state.get("debug_total_attempts", 0) + 1
        debug_reasons = state.get("debug_reasons", []) + [reason]
        generated_codes = state.get("generated_codes", []) + [code]

        return {
            "generated_codes": generated_codes,
            "debug_attempts": debug_attempts,
            "debug_total_attempts": debug_total_attempts,
            "debug_reasons": debug_reasons,
        }

    async def summarizer(state: TableProcessingState) -> TableProcessingState:
        """Summarize results using TableReAct Strategy."""
        log.info("🔍🔍 Summarizer Node (TableReAct THINK → ACTION → OBSERVE)")
        model = state.request.model or state.get("model", "deepseek-v3.2")

        agent = create_table_react_agent(
            name="summarizer",
            model_name=model,
            max_retries=MAX_REACT_STEPS,
            parser_type="json",
        )

        state = await agent.execute(state=state)
        agent_result = state.agent_results.get("summarizer", {})
        results = agent_result.get("results", {})
        summary = results.get("answer", "")
        react_trace = results.get("react_trace", [])

        if state.get("llm_tracker"):
            summary_messages = [
                {"role": "system", "content": "Summarize the following ReAct trace briefly."},
                {"role": "user", "content": f"ReAct Trace: {json.dumps(react_trace, ensure_ascii=False)}"},
            ]
            local_summarizer_response = await state["llm_tracker"](summary_messages)
            summarizing_trace_summary = local_summarizer_response.content.strip()
            log.info(f"🔍🔍 Local Summarizer ReAct Trace Summary:\n{summarizing_trace_summary}")
        else:
            summarizing_trace_summary = ""

        log.info(f"Summarizer 原始输出：{summary}")

        return {
            "summary": summary,
            "summarizing_trace_summary": summarizing_trace_summary,
            "execution_time": state.get("execution_time", 0.0) + results.get("execution_time", 0.0),
        }

    async def finalizer(state: TableProcessingState) -> TableProcessingState:
        """Finalize and write evaluation results."""
        log.info("✅️ 进入终止节点，写入评估结果并结束流程")
        try:
            write_eval_result(state)
        except Exception as e:
            log.error(f"写入评估结果失败: {e}")
        return state

    # =======================================================================
    # Conditional edges
    # =======================================================================

    def should_debug(state: TableProcessingState) -> Literal["debugger", "summarizer", "finalizer"]:
        """根据评分与有效性决定是否进入调试节点"""
        debug_attempts = state.get("debug_attempts", 0)
        valid = state.get("valid", False)

        if not valid and debug_attempts < MAX_DEBUG_ATTEMPTS:
            log.info(f"🔄 任务未通过验证，进入调试节点（debug_attempts={debug_attempts}）")
            return "debugger"

        if not valid and debug_attempts >= MAX_DEBUG_ATTEMPTS:
            log.warning(f"⚠️ 达到最大调试次数 ({debug_attempts})，强制终止")
            return "finalizer"

        log.info("✅ 任务通过验证，进入总结节点")
        if state.get("attempts", 0) >= MAX_GENERATE_ATTEMPTS:
            log.warning(f"⚠️ 达到最大重试次数 ({state.get('attempts', 0)})，强制终止")
            return "finalizer"
        return "summarizer"

    def should_decomposite(state: TableProcessingState) -> Literal["decompositer", "generator"]:
        """根据任务复杂度决定是否进入分解节点"""
        is_dag = state.get("is_dag", False)
        if is_dag:
            log.info("🔄 任务复杂，进入分解节点")
            return "decompositer"
        else:
            log.info("✅ 任务简单，跳过分解节点")
            return "generator"

    # =======================================================================
    # Register nodes and edges
    # =======================================================================

    nodes = {
        "intent_understanding": intent_understanding,
        "data_profiling": data_profiling,
        "decompositer": decompositer,
        "generator": generator,
        "evaluator": evaluator,
        "summarizer": summarizer,
        "debugger": debugger,
        "finalizer": finalizer,
        "_end_": lambda state: state,
    }

    edges = [
        ("intent_understanding", "data_profiling"),
        ("decompositer", "generator"),
        ("generator", "evaluator"),
        ("debugger", "evaluator"),
        ("summarizer", "finalizer"),
        ("finalizer", "_end_"),
    ]

    conditional_edges = {
        "evaluator": should_debug,
        "data_profiling": should_decomposite,
    }

    builder.add_nodes(nodes).add_edges(edges).add_conditional_edges(conditional_edges)
    return builder
