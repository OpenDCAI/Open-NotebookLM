from typing import TypedDict, List, Dict, Optional, Literal
from langgraph.graph import StateGraph, END
from dm_components.config import logger
import json

# --- 1. 定义状态 ---
class InsightState(TypedDict):
    agent_base: object
    initial_goal: str
    branch_depth: int
    max_questions: int

    pending_root_questions: List[str]
    current_question: str
    current_branch_iteration: int
    
    # 路由控制标记
    next_action: Literal["continue_deep", "next_root", "summarize"]

    insights_history: List[Dict]
    final_summary: Optional[str]

class InsightWorkflow:
    def __init__(self, agent_base, branch_depth=3):
        self.agent_base = agent_base
        self.branch_depth = branch_depth
        self.app = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(InsightState)

        # 定义节点
        workflow.add_node("init_node", self.initialize_workflow)
        workflow.add_node("answer_node", self.answer_question)
        workflow.add_node("logic_node", self.decide_next_step) # 核心逻辑指挥中心
        workflow.add_node("summarize_node", self.summarize_insights)

        # 连线
        workflow.set_entry_point("init_node")
        workflow.add_edge("init_node", "answer_node")
        workflow.add_edge("answer_node", "logic_node")

        # 根据 logic_node 计算出的 next_action 进行分发
        workflow.add_conditional_edges(
            "logic_node",
            lambda state: state["next_action"],
            {
                "continue_deep": "answer_node",
                "next_root": "answer_node",
                "summarize": "summarize_node"
            }
        )
        workflow.add_edge("summarize_node", END)

        return workflow.compile()

    # --- Node 实现 ---

    def initialize_workflow(self, state: InsightState) -> Dict:
        logger.info("### NODE: Initializing Workflow ###")
        agent = state['agent_base']
        root_qs = agent.recommend_questions(
            prompt_method="basic",
            n_questions=state['max_questions']
        )

        if not root_qs:
            logger.error("No root questions generated.")
            return {"next_action": "summarize", "current_question": "End"}

        return {
            "pending_root_questions": root_qs[1:],
            "current_question": root_qs[0],
            "current_branch_iteration": 0,
            "insights_history": [],
            "next_action": "continue_deep" # 初始动作
        }

    def answer_question(self, state: InsightState) -> Dict:
        agent = state['agent_base']
        q = state['current_question']
        depth = state['current_branch_iteration']
        
        logger.info(f"### NODE: Answering Question (Depth: {depth}) ###")
        logger.info(f"Question: {q}")

        _, insight_dict = agent.answer_question(
            q, 
            prompt_code_method="single",
            prompt_interpret_method="basic"
        )
        
        new_history = state.get('insights_history', []) + [insight_dict]
        return {"insights_history": new_history}

    def decide_next_step(self, state: InsightState) -> Dict:
        """
        这个节点替代了原来的 recommend_node + should_continue。
        它负责判断：是生成追问、切换根问题、还是结束。
        """
        logger.info("### NODE: Deciding Next Step ###")
        agent = state['agent_base']
        
        # 1. 检查是否需要深挖 (Deep Dive)
        if state['current_branch_iteration'] + 1 < state['branch_depth']:
            logger.info(f"Action: Generating follow-up (Depth {state['current_branch_iteration'] + 1})")
            
            last_insight = state['insights_history'][-1]
            next_qs = agent.recommend_questions(
                n_questions=state['max_questions'],
                insights_history=[last_insight]
            )
            
            # 安全解析问题
            if next_qs:
                # 假设 agent.select_a_question 返回索引
                idx = agent.select_a_question(next_qs)
                return {
                    "current_question": next_qs[idx],
                    "current_branch_iteration": state['current_branch_iteration'] + 1,
                    "next_action": "continue_deep"
                }
            else:
                logger.warning("No follow-up questions generated, trying to switch root.")

        # 2. 检查是否有待处理的根问题 (Next Root)
        if state['pending_root_questions']:
            next_root = state['pending_root_questions'][0]
            logger.info(f"Action: Switching to next root question: {next_root}")
            return {
                "current_question": next_root,
                "pending_root_questions": state['pending_root_questions'][1:],
                "current_branch_iteration": 0,
                "next_action": "next_root"
            }

        # 3. 都没有则结束
        logger.info("Action: All tasks completed.")
        return {"next_action": "summarize"}

    def summarize_insights(self, state: InsightState) -> Dict:
        logger.info("### NODE: Summarizing ###")
        agent = state['agent_base']
        summary = agent.summarize(state['insights_history'])
        return {"final_summary": summary}

    # --- Run 方法保持不变 ---
    def run(self, initial_goal: str, max_questions: int = 3, output_json_path: Optional[str] = None):
        initial_state = {
            "agent_base": self.agent_base,
            "initial_goal": initial_goal,
            "branch_depth": self.branch_depth,
            "max_questions": max_questions,
            "pending_root_questions": [],
            "current_question": "",
            "current_branch_iteration": 0,
            "insights_history": [],
            "final_summary": None,
            "next_action": "continue_deep"
        }
        # ... invoke and save logic ...
        final_state = self.app.invoke(initial_state)
        return final_state