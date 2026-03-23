# orchestrator_workflow.py
import os
import json
import re
import numpy as np
from typing import Dict, Any, List, TypedDict, Optional
from langgraph.graph import StateGraph, END

from dm_components import prompts
from dm_components.config import logger
from dm_components.agents.base_agent import AgentBase
from dm_components.agents.datasource_agent import DataSourceAgent
from dm_components.utils import agent_utils as au


# =============================================================================
# Hybrid Scoring Functions
# =============================================================================

def calculate_objective_score(agent: DataSourceAgent) -> float:
    """
    Calculate objective data quality and richness score.
    
    Components:
    - Data quality score (based on missing rate)
    - Data richness score (based on columns, rows, unique values)
    - Temporal dimension score (presence of time-related columns)
    
    Returns:
        Score between 0-10
    """
    df = agent.data
    
    # 1. Data quality score (0-10) - lower missing rate = higher score
    if len(df) == 0:
        return 0.0
    
    missing_rate = df.isnull().sum().sum() / (len(df) * len(df.columns)) if len(df.columns) > 0 else 1
    quality_score = 10 * (1 - min(missing_rate, 1))
    
    # 2. Data richness score (0-10)
    # - Column diversity: more columns = richer data
    # - Row count: logarithmic scale to handle large datasets
    # - Unique value ratio: higher ratio suggests more information
    col_score = min(len(df.columns) * 0.5, 5)  # Max 5 points for columns
    row_score = min(np.log10(max(len(df), 1)) * 1.5, 3)  # Max 3 points for rows
    
    # Average unique ratio across columns
    unique_ratios = []
    for col in df.columns:
        try:
            unique_ratio = df[col].nunique() / len(df) if len(df) > 0 else 0
            unique_ratios.append(unique_ratio)
        except:
            continue
    avg_unique_ratio = np.mean(unique_ratios) if unique_ratios else 0
    diversity_score = min(avg_unique_ratio * 5, 2)  # Max 2 points
    
    richness_score = col_score + row_score + diversity_score
    
    # 3. Temporal dimension score (0-10)
    temporal_keywords = ['date', 'time', 'timestamp', 'datetime', 'year', 'month', 'day', 'created', 'updated']
    has_temporal = any(
        any(kw in col.lower() for kw in temporal_keywords)
        for col in df.columns
    )
    temporal_score = 10 if has_temporal else 0
    
    # Combine scores (weighted average)
    final_score = (quality_score * 0.4 + richness_score * 0.4 + temporal_score * 0.2)
    
    return round(min(final_score, 10), 2)


def calculate_semantic_relevance(schema_str: str, global_goal: str) -> float:
    """
    Calculate semantic relevance based on keyword overlap.
    
    Uses simple keyword matching between schema and goal.
    
    Returns:
        Score between 0-10
    """
    if not global_goal or not schema_str:
        return 5.0  # Neutral score if no goal provided
    
    # Extract keywords from goal (simple tokenization)
    goal_words = set(
        word.lower().strip('.,!?;:()[]{}"\' ')
        for word in global_goal.split()
        if len(word) > 2
    )
    
    # Extract words from schema
    schema_words = set(
        word.lower().strip('.,!?;:()[]{}"\' ')
        for word in schema_str.split()
        if len(word) > 2
    )
    
    if not goal_words:
        return 5.0
    
    # Calculate overlap
    overlap = len(goal_words & schema_words)
    relevance_ratio = overlap / len(goal_words)
    
    # Scale to 0-10
    return round(min(relevance_ratio * 15, 10), 2)  # Slightly generous scaling


def calculate_hybrid_score(
    agent: DataSourceAgent, 
    global_goal: str,
    llm_score: float,
    weights: Dict[str, float] = None
) -> float:
    """
    Calculate final hybrid score combining all metrics.
    
    Args:
        agent: DataSourceAgent instance
        global_goal: Analysis goal
        llm_score: Score from LLM evaluation (0-10)
        weights: Custom weights for each component
        
    Returns:
        Final score between 0-10
    """
    if weights is None:
        weights = {
            "objective": 0.4,
            "semantic": 0.3,
            "llm": 0.3
        }
    
    objective_score = calculate_objective_score(agent)
    semantic_score = calculate_semantic_relevance(agent.schema_str, global_goal)
    
    final_score = (
        weights["objective"] * objective_score +
        weights["semantic"] * semantic_score +
        weights["llm"] * llm_score
    )
    
    return round(final_score, 2)


class OrchestratorState(TypedDict):
    """
    Main workflow state definition.
    
    Attributes:
        data_agents: List of DataSourceAgent instances
        initial_reports: Reports from independent analysis phase
        annotated_reports: Reports with cross-agent annotations
        numerical_crossover_ideas: Generated questions for cross-dataset analysis
        numerical_crossover_results: Results from cross-dataset calculations
        pred_insights: Final synthesized insights
        pred_summary: Final executive summary
        detailed_appendix: Detailed information for benchmark comparison (NEW)
        orchestrator_agent: Orchestrator agent instance
        global_goal: Overall analysis objective
        data_registry: Mapping of agent names to file paths
        background_knowledge_pool: List of background information from non-tabular sources (NEW)
        output_mode: Output mode - "concise" or "detailed" (NEW)
    """
    data_agents: List[DataSourceAgent]
    initial_reports: List[Dict[str, Any]]
    annotated_reports: List[Dict[str, Any]]
    numerical_crossover_ideas: List[str]
    numerical_crossover_results: List[Dict[str, Any]]
    pred_insights: List[str]
    pred_summary: str
    detailed_appendix: Dict[str, Any]  # NEW
    raw_single_insights: List[Dict[str, Any]]  # NEW: Raw insights from single-source analysis
    raw_crossover_insights: List[Dict[str, Any]]  # NEW: Raw insights from crossover analysis
    orchestrator_agent: Any 
    global_goal: str
    data_registry: Dict[str, str]
    background_knowledge_pool: List[Dict[str, Any]]  # NEW
    output_mode: str  # NEW: "concise" or "detailed"


class OrchestratorWorkflow:
    """
    Main orchestrator workflow using LangGraph for multi-agent analysis.
    """
    
    def __init__(self, data_agents: List[DataSourceAgent], global_goal: str = ""):
        """
        Initialize the orchestrator workflow.
        
        Args:
            data_agents: List of DataSourceAgent instances
            global_goal: Overall analysis objective
        """
        self.data_agents = data_agents
        self.global_goal = global_goal
        self.orchestrator_agent = self._create_orchestrator_agent(data_agents)
        self.data_registry = {agent.name: agent.original_file_path for agent in data_agents}
        self.app = self._build_graph()

    def _create_orchestrator_agent(self, data_agents: List[DataSourceAgent]) -> Any:
        """
        Create orchestrator agent with shared resources.
        
        Args:
            data_agents: List of data agents for configuration reference
            
        Returns:
            Orchestrator agent object
        """
        if not data_agents:
            return None
        
        orchestrator = type('OrchestratorAgent', (object,), {})()
        
        # Use the first agent's configuration for consistency
        orchestrator.chat_model = au.get_chat_model(
            data_agents[0].agent_config['model_name'],
            data_agents[0].agent_config['temperature'],
            api_key=data_agents[0].agent_config.get('api_key'),
            base_url=data_agents[0].agent_config.get('base_url')
        )
        
        # Create shared AgentBase for cross-dataset analysis
        orchestrator.crossover_poirot = AgentBase(
            model_name=data_agents[0].agent_config['model_name'],
            savedir=os.path.join(data_agents[0].agent_config['base_savedir'], "_crossover_agent"),
            goal="Perform cross-dataset numerical analysis to answer specific questions.",
            verbose=True,
            temperature=data_agents[0].agent_config['temperature'],
            n_retries=data_agents[0].agent_config['n_retries'],
        )
        
        return orchestrator

    def _build_graph(self):
        """
        Build the LangGraph state machine.
        
        Returns:
            Compiled LangGraph application
        """
        workflow = StateGraph(OrchestratorState)

        # Define all processing nodes
        workflow.add_node("initial_data_profile", self.initial_data_profile_node)
        workflow.add_node("heuristic_exploration", self.heuristic_exploration_node)
        workflow.add_node("formal_annotation", self.formal_annotation_node)
        workflow.add_node("background_crossover", self.background_crossover_node)
        workflow.add_node("numerical_crossover", self.numerical_crossover_node)
        workflow.add_node("viewpoint_crossover", self.viewpoint_crossover_node)

        # Define execution flow
        workflow.set_entry_point("initial_data_profile")
        workflow.add_edge("initial_data_profile", "heuristic_exploration")
        workflow.add_edge("heuristic_exploration", "formal_annotation")
        workflow.add_edge("formal_annotation", "background_crossover")
        workflow.add_edge("background_crossover", "numerical_crossover")
        workflow.add_edge("numerical_crossover", "viewpoint_crossover")
        workflow.add_edge("viewpoint_crossover", END)

        return workflow.compile()

    def initial_data_profile_node(self, state: OrchestratorState) -> Dict[str, Any]:
        """
        Step 1A: Generate enhanced data profiles and preliminary evaluation using hybrid scoring.
        
        Uses a combination of:
        - Objective metrics (data quality, richness, temporal dimensions)
        - Semantic relevance (keyword matching with goal)
        - LLM evaluation (subjective assessment)
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with data profiles and hybrid scores
        """
        logger.info("\n===== STEP 1A: Enhanced Data Profiling with Hybrid Scoring =====")
        agents = state['data_agents']
        global_goal = state['global_goal']
        
        for agent in agents:
            # 1. Calculate objective score
            objective_score = calculate_objective_score(agent)
            logger.info(f"Agent {agent.name} - Objective Score: {objective_score}/10")
            
            # 2. Calculate semantic relevance score
            semantic_score = calculate_semantic_relevance(agent.schema_str, global_goal)
            logger.info(f"Agent {agent.name} - Semantic Relevance Score: {semantic_score}/10")
            
            # 3. Get LLM evaluation score
            prompt = prompts.PRELIMINARY_EVAL_PROMPT.format(
                global_goal=global_goal,
                data_profile=agent.schema_str
            )
            response = agent.chat_model(prompt)
            response_content = response.content if hasattr(response, 'content') else str(response)
            
            tags = au.extract_html_tags(response_content, ["relevance", "reasoning", "priority"])
            
            # Parse LLM relevance score (0-10)
            try:
                llm_score = float(tags.get("relevance", ["5"])[0])
                llm_score = min(max(llm_score, 0), 10)  # Clamp to 0-10
            except (ValueError, IndexError):
                llm_score = 5.0
            logger.info(f"Agent {agent.name} - LLM Score: {llm_score}/10")
            
            # 4. Calculate final hybrid score
            hybrid_score = calculate_hybrid_score(
                agent=agent,
                global_goal=global_goal,
                llm_score=llm_score
            )
            
            # 5. Determine priority based on hybrid score
            if hybrid_score >= 7:
                agent.preliminary_priority = "High"
            elif hybrid_score >= 4:
                agent.preliminary_priority = "Medium"
            else:
                agent.preliminary_priority = "Low"
            
            # Store scores for later use
            agent.hybrid_score = hybrid_score
            agent.objective_score = objective_score
            agent.semantic_score = semantic_score
            agent.llm_score = llm_score
            
            logger.info(f"Agent {agent.name} - FINAL Hybrid Score: {hybrid_score}/10 "
                       f"-> Priority: {agent.preliminary_priority}")

        return {"data_agents": agents}

    def heuristic_exploration_node(self, state: OrchestratorState) -> Dict[str, Any]:
        """
        Step 1B: Each agent performs independent deep-dive analysis.
        Args:
            state: Current workflow state
        Returns:
            Updated state with initial reports
        """
        logger.info("\n===== STEP 1B: Independent Deep-Dive Analysis =====")
        agents = state['data_agents']
        initial_reports = [agent.analyze_self() for agent in agents]
        return {"initial_reports": initial_reports}


    def formal_annotation_node(self, state: OrchestratorState) -> Dict[str, Any]:
        """
        Step 2: Formal importance labeling based on analysis quality.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with formal priority labels
        """
        logger.info("===== STEP 2: Formal Importance Labeling =====")
        
        agents = state['data_agents']
        updated_reports = state['initial_reports'].copy()
        
        for i, agent in enumerate(agents):
            summary = state['initial_reports'][i]['summary']
            
            prompt = prompts.FORMAL_ANNOTATION_PROMPT.format(
                global_goal=state['global_goal'],
                schema=agent.agent_base.schema,
                exploration_summary=summary
            )
            
            response = agent.chat_model(prompt)
            response_content = response.content if hasattr(response, 'content') else str(response)
            
            tags = au.extract_html_tags(response_content, ["richness", "alignment", "label", "justification"])
            print(tags)
            
            # Map label to priority logic
            label = tags.get("label", ["Secondary"])[0]
            agent.final_priority = "High" if label == "Primary" else "Medium"
            agent.importance_label = label
            
            justification = tags.get("justification", [""])[0][:100]  # Truncate for logging
            logger.info(f"Agent {agent.name} labeled as: {agent.final_priority} "
                       f"({label}) - Justification: {justification}...")
            
            # Update report with formal label
            updated_reports[i]['formal_label'] = label
            updated_reports[i]['formal_priority'] = agent.final_priority

        return {
            "data_agents": agents,
            "initial_reports": updated_reports
        }


    def background_crossover_node(self, state: OrchestratorState) -> Dict[str, Any]:
        """
        Step 3: Background crossover with priority-weighted annotation.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with annotated reports and crossover questions
        """
        logger.info("\n===== STEP 3: Background Crossover & Idea Generation (Priority-Weighted) =====")
        
        initial_reports = state['initial_reports']
        agents = state['data_agents']
        orchestrator = state['orchestrator_agent']
        
        # 1. Stratify by priority
        high_reports = [r for r in initial_reports if r.get('formal_priority') == "High"]
        other_reports = [r for r in initial_reports if r.get('formal_priority') != "High"]
        
        context_for_ideation = "=== [CORE DATASETS - MUST ANALYZE] ===\n"
        
        # 2. Process high-priority datasets (full information + deep annotations)
        for report in high_reports:
            context_for_ideation += f"\n[PRIMARY] Agent: {report['agent_name']}\nSummary: {report['summary']}\n"
            
            # Collect annotations from other agents
            annotations = []
            for annotator in agents:
                if annotator.name != report['agent_name']:
                    annotation = annotator.annotate_other_agent_summary(report)
                    if annotation['comment']:
                        annotations.append(annotation)
                        context_for_ideation += f"  - Critical Note by [{annotator.name}]: {annotation['comment']}\n"
            
            # Store annotations in report
            report['annotations'] = annotations
        
        context_for_ideation += "\n=== [SUPPORTING DATASETS - AUXILIARY ONLY] ===\n"
        
        # 3. Process low-priority datasets (compressed information, background only)
        for report in other_reports:
            brief_summary = report['summary'][:300] + "..." if len(report['summary']) > 300 else report['summary']
            context_for_ideation += f"[SECONDARY] Agent: {report['agent_name']}\nBrief: {brief_summary}\n"
        
        # 4. Generate cross-dataset analytical questions
        prompt = prompts.NUMERICAL_CROSSOVER_IDEATION_PROMPT.format(
            global_goal=state['global_goal'],
            context=context_for_ideation
        )
        
        response = orchestrator.chat_model(prompt)
        response_content = response.content if hasattr(response, 'content') else str(response)

        ideas = au.extract_html_tags(response_content, ["question"]).get("question", [])
        logger.info(f"Generated {len(ideas)} cross-dataset analytical questions after prioritizing High Priority datasets.")

        return {
            "annotated_reports": initial_reports,
            "numerical_crossover_ideas": ideas
        }

    def numerical_crossover_node(self, state: OrchestratorState) -> Dict[str, Any]:
        """
        Step 4: Execute numerical cross-dataset calculations with enhanced profile info.
        
        Now includes statistical profiles of each dataset to help code generation
        make better decisions about data types, ranges, and join strategies.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with numerical crossover results
        """
        logger.info("\n===== STEP 4: Numerical Cross-Dataset Calculation (with Profile Info) =====")
        
        ideas = state['numerical_crossover_ideas']
        if not ideas:
            logger.info("No numerical crossover questions generated, skipping this step.")
            return {"numerical_crossover_results": []}
        
        agents = state['data_agents']
        crossover_agent = state['orchestrator_agent'].crossover_poirot
        results = []
        schemas = []
        paths = []
        profiles = []  # NEW: Collect profile information

        for agent in agents:
            schemas.append(agent.agent_base.schema)
            paths.append(agent.original_file_path)
            # Collect profile information for each dataset
            profiles.append(agent.profile if hasattr(agent, 'profile') else "{}")

        for question in ideas:
            logger.info(f"\nProcessing numerical crossover question: {question}")

            crossover_agent.multi_schema = schemas
            crossover_agent.multi_dataset_path = paths
            crossover_agent.multi_profile = profiles  # NEW: Pass profile info

            # Execute cross-dataset analysis
            try:
                _, insight_dict = crossover_agent.answer_question(
                    question, 
                    prompt_code_method="multi_with_paths"
                )
                results.append(insight_dict)
            except Exception as e:
                logger.error(f"Failed to process crossover question: {e}")
                results.append({
                    "question": question,
                    "answer": f"Analysis failed: {str(e)}",
                    "error": True
                })
        
        logger.info(f"Completed {len(results)} numerical crossover calculations.")
        return {"numerical_crossover_results": results}

    def viewpoint_crossover_node(self, state: OrchestratorState) -> Dict[str, Any]:
        """
        Step 5: Viewpoint crossover - synthesize all information into final report.
        
        Supports two output modes:
        - concise: Brief insights with truncated details
        - detailed: Full information with detailed_appendix for benchmark comparison
        
        Also supports background knowledge injection from non-tabular sources.
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with final insights, summary, and optional detailed_appendix
        """
        logger.info("\n===== STEP 5: Viewpoint Crossover & Final Synthesis =====")
        
        orchestrator = state['orchestrator_agent']
        annotated_reports = state['annotated_reports']
        numerical_results = state['numerical_crossover_results']
        output_mode = state.get('output_mode', 'concise')
        background_pool = state.get('background_knowledge_pool', [])
        
        logger.info(f"Output mode: {output_mode}")
        
        # Build comprehensive context
        full_context = ""
        
        for report in annotated_reports:
            full_context += f"--- Analysis Report Source: {report['agent_name']} ---\n"
            
            # In concise mode, limit summary length
            summary = report['summary']
            if output_mode == 'concise' and len(summary) > 500:
                summary = summary[:500] + "... [truncated]"
            full_context += f"Preliminary Summary: {summary}\n"
            
            if report.get('annotations'):
                full_context += "Cross-Agent Annotations:\n"
                for ann in report['annotations']:
                    comment = ann['comment']
                    if output_mode == 'concise' and len(comment) > 200:
                        comment = comment[:200] + "..."
                    full_context += f"  - [{ann['author_agent']}]: {comment}\n"
            
            if report.get('formal_label'):
                full_context += f"Formal Classification: {report['formal_label']} ({report.get('formal_priority', 'Medium')})\n"
            
            full_context += "\n"
        
        if numerical_results:
            full_context += "--- Cross-Domain Numerical Analysis ---\n"
            for res in numerical_results:
                full_context += f"Question: {res.get('question', 'N/A')}\n"
                answer = res.get('answer', 'N/A')
                if output_mode == 'concise' and isinstance(answer, str) and len(answer) > 300:
                    answer = answer[:300] + "..."
                full_context += f"Findings: {answer}\n"
                
                if res.get('error'):
                    full_context += f"Status: ERROR\n"
                
                full_context += "\n"
        
        # Build background information string
        background_info = "No additional background information available."
        if background_pool:
            bg_parts = []
            for bg in background_pool:
                if isinstance(bg, dict):
                    source = bg.get('source', 'Unknown')
                    content = bg.get('content', '')
                    source_type = bg.get('source_type', 'unknown')
                    # Limit each background item
                    if output_mode == 'concise' and len(content) > 500:
                        content = content[:500] + "... [truncated]"
                    bg_parts.append(f"[{source_type}] {os.path.basename(source)}:\n{content}")
            background_info = "\n\n".join(bg_parts) if bg_parts else background_info

        # Generate final synthesis using the appropriate prompt
        if hasattr(prompts, 'FINAL_PROMPT_TEMPLATE_WITH_MODES'):
            prompt = prompts.FINAL_PROMPT_TEMPLATE_WITH_MODES.format(
                full_context=full_context,
                background_info=background_info,
                output_mode=output_mode
            )
        else:
            # Fallback to original prompt
            prompt = prompts.FINAL_PROMPT_TEMPLATE.format(full_context=full_context)
        
        response = orchestrator.chat_model(prompt)
        response_content = response.content if hasattr(response, 'content') else str(response)

        # Parse response
        pred_insights = []
        pred_summary = ""
        detailed_appendix = {}
        
        # Collect all raw insights from single-source analysis and crossover analysis
        all_single_insights = []
        all_crossover_insights = []
        
        # Extract single-source insights
        for report in annotated_reports:
            agent_name = report.get('agent_name', 'Unknown')
            # Get key_metrics (insights) from each agent's report
            agent_insights = report.get('key_metrics', [])
            logger.debug(f"Extracting insights from {agent_name}: found {len(agent_insights)} items")
            
            for insight in agent_insights:
                if isinstance(insight, str):
                    all_single_insights.append({
                        "source": agent_name,
                        "insight": insight
                    })
                elif isinstance(insight, dict):
                    # insights_history format: {question, answer, insight, justification, ...}
                    # Prefer 'insight' field, fallback to 'answer', then to string representation
                    insight_text = insight.get('insight') or insight.get('answer') or str(insight)
                    question = insight.get('question', '')
                    
                    all_single_insights.append({
                        "source": agent_name,
                        "insight": insight_text,
                        "question": question if question else None
                    })
                else:
                    # Fallback for any other type
                    all_single_insights.append({
                        "source": agent_name,
                        "insight": str(insight)
                    })
            
            logger.debug(f"Extracted {len([i for i in all_single_insights if i['source'] == agent_name])} insights from {agent_name}")
        
        # Extract crossover insights
        for res in numerical_results:
            question = res.get('question', 'N/A')
            answer = res.get('answer', 'N/A')
            if not res.get('error') and answer != 'N/A':
                all_crossover_insights.append({
                    "question": question,
                    "finding": answer
                })
        
        try:
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                result = json.loads(json_str)
                pred_insights = result.get("insights", [])
                pred_summary = result.get("summary", "")
                
                # Extract detailed_appendix if in detailed mode
                if output_mode == 'detailed':
                    detailed_appendix = result.get("detailed_appendix", {})
                    # If LLM didn't provide, build it ourselves
                    if not detailed_appendix:
                        detailed_appendix = {
                            "full_reports": [
                                {
                                    "agent_name": r['agent_name'],
                                    "summary": r['summary'],
                                    "insights": r.get('key_metrics', []),
                                    "annotations": r.get('annotations', [])
                                }
                                for r in annotated_reports
                            ],
                            "crossover_results": numerical_results,
                            "background_info": background_pool
                        }
            else:
                # Fallback to simple parsing
                logger.warning("Could not parse JSON response, using fallback logic")
                pred_insights = [
                    line.strip().lstrip('- ') 
                    for line in response_content.split('\n') 
                    if line.strip() and line.strip().startswith('-')
                ]
                pred_summary = "Auto-generated summary from analysis."
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}")
            pred_insights = [
                line.strip().lstrip('- ') 
                for line in response_content.split('\n') 
                if line.strip() and line.strip().startswith('-')
            ]
            pred_summary = "Auto-generated summary from analysis."

        # Log final results
        logger.info("\n===== Final Synthesis Report =====")
        logger.info(f"Output Mode: {output_mode}")
        logger.info(f"Executive Summary: {pred_summary[:200]}...")
        logger.info(f"Number of Synthesized Insights (categorized): {len(pred_insights)}")
        logger.info(f"Number of Raw Single-Source Insights: {len(all_single_insights)}")
        logger.info(f"Number of Raw Crossover Insights: {len(all_crossover_insights)}")
        
        for i, insight in enumerate(pred_insights[:5], 1):
            logger.info(f"{i}. {insight[:100]}...")
        
        if len(pred_insights) > 5:
            logger.info(f"... and {len(pred_insights) - 5} more insights")
        
        if detailed_appendix:
            logger.info(f"Detailed appendix included with {len(detailed_appendix)} sections")

        # Log what we're returning
        logger.info(f"\nReturning from viewpoint_crossover_node:")
        logger.info(f"  - raw_single_insights: {len(all_single_insights)} items")
        logger.info(f"  - raw_crossover_insights: {len(all_crossover_insights)} items")
        if all_single_insights:
            logger.info(f"  - Sample single insight: {all_single_insights[0]}")
        if all_crossover_insights:
            logger.info(f"  - Sample crossover insight: {all_crossover_insights[0]}")

        return {
            "pred_insights": pred_insights,  # Synthesized insights (categorized by Trend/Comparison/Extreme/Attribution)
            "pred_summary": pred_summary,
            "detailed_appendix": detailed_appendix,
            "raw_single_insights": all_single_insights,  # All single-source insights
            "raw_crossover_insights": all_crossover_insights  # All crossover insights
        }

    def run(
        self, 
        output_mode: str = "concise",
        background_knowledge_pool: Optional[List[Dict[str, Any]]] = None
    ):
        """
        Execute the complete workflow.
        
        Args:
            output_mode: "concise" for brief output, "detailed" for full output with appendix
            background_knowledge_pool: List of background info dicts from non-tabular sources
        
        Returns:
            Tuple of (insights list, summary string) or
            Tuple of (insights list, summary string, detailed_appendix) if detailed mode
        """
        # Initialize workflow state
        initial_state = {
            "data_agents": self.data_agents,
            "data_registry": self.data_registry,
            "orchestrator_agent": self.orchestrator_agent,
            "global_goal": self.global_goal,
            "initial_reports": [],
            "annotated_reports": [],
            "numerical_crossover_ideas": [],
            "numerical_crossover_results": [],
            "pred_insights": [],
            "pred_summary": "",
            "detailed_appendix": {},
            "raw_single_insights": [],  # Initialize raw insights
            "raw_crossover_insights": [],  # Initialize raw crossover insights
            "output_mode": output_mode,
            "background_knowledge_pool": background_knowledge_pool or []
        }

        logger.info(f"Starting workflow execution (output_mode={output_mode})...")
        
        # Execute the LangGraph state machine
        final_state = self.app.invoke(initial_state)
        
        logger.info("Workflow execution completed successfully.")
        
        # Debug: log all keys in final_state
        logger.info(f"Final state keys: {list(final_state.keys())}")
        
        # Extract final results
        pred_insights = final_state.get("pred_insights", [])
        pred_summary = final_state.get("pred_summary", "")
        detailed_appendix = final_state.get("detailed_appendix", {})
        raw_single_insights = final_state.get("raw_single_insights", [])
        raw_crossover_insights = final_state.get("raw_crossover_insights", [])
        
        # Log extracted raw insights
        logger.info(f"Extracted from final_state:")
        logger.info(f"  - raw_single_insights: {len(raw_single_insights)} items")
        logger.info(f"  - raw_crossover_insights: {len(raw_crossover_insights)} items")
        
        # Debug: check if keys exist but are empty
        if "raw_single_insights" in final_state:
            logger.info(f"  - raw_single_insights key exists, value type: {type(final_state['raw_single_insights'])}, length: {len(final_state.get('raw_single_insights', []))}")
        else:
            logger.warning("  - raw_single_insights key NOT FOUND in final_state!")
        
        if "raw_crossover_insights" in final_state:
            logger.info(f"  - raw_crossover_insights key exists, value type: {type(final_state['raw_crossover_insights'])}, length: {len(final_state.get('raw_crossover_insights', []))}")
        else:
            logger.warning("  - raw_crossover_insights key NOT FOUND in final_state!")
        
        # Combine crossover insights into the same format as single insights
        combined_crossover = []
        for item in raw_crossover_insights:
            if isinstance(item, dict):
                finding = item.get('finding', item.get('answer', 'N/A'))
                question = item.get('question', 'N/A')
                combined_crossover.append({
                    "source": "crossover",
                    "insight": finding,
                    "question": question
                })
        
        # Combine all raw insights
        all_raw_insights = raw_single_insights + combined_crossover
        
        logger.info(f"Combined raw insights: {len(all_raw_insights)} total (single: {len(raw_single_insights)}, crossover: {len(combined_crossover)})")

        # Return all insights types
        return {
            "synthesized_insights": pred_insights,  # Categorized insights (Trend/Comparison/Extreme/Attribution)
            "raw_insights": all_raw_insights,  # Combined all raw insights
            "summary": pred_summary,
            "detailed_appendix": detailed_appendix if output_mode == "detailed" else {}
        }

    def generate_markdown_report(self, final_state: Dict[str, Any], filename: str) -> str:
        """
        Generate a Markdown report from the final workflow state.
        
        Args:
            final_state: Complete workflow state
            filename: Output file path
            
        Returns:
            Path to generated report file
        """
        logger.info(f"Generating Markdown report: {filename}")
        
        # Create simplified state for report generation
        simplified_state = {}
        
        for key, value in final_state.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                simplified_state[key] = value
            elif isinstance(value, (list, dict)):
                try:
                    json.dumps(value)
                    simplified_state[key] = value
                except (TypeError, ValueError):
                    simplified_state[key] = f"[Non-serializable {type(value).__name__} object]"
            else:
                simplified_state[key] = f"[{type(value).__name__} object]"
        
        state_str = json.dumps(simplified_state, indent=2, ensure_ascii=False)
        
        # Generate report using LLM
        chat_model = au.get_chat_model("gpt-4o", 0)
        prompt = prompts.REPORT_GENERATION_PROMPT.format(state_str=state_str)
        report_content = chat_model(prompt).content
        
        # Save report