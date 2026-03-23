import os
import json
import copy
import tempfile
import pandas as pd
from PIL import Image


from dm_components import prompts
from dm_components.config import logger
from dm_components.workflows.insight_workflow import InsightWorkflow
from dm_components.agents.base_agent import AgentBase
from dm_components.utils import agent_utils as au
from dm_components.utils.dataloader_utils import DataSourceReader


from typing import TypedDict, List, Dict, Optional, Any
from langchain.schema import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver



class DataSourceAgent:
    """
    Agent representing a single data source.
    Wraps an AgentBase instance internally for analysis capabilities.
    """
    
    def __init__(self, name: str, data: pd.DataFrame, original_file_path: str, 
                 external_knowledge: str, agent_config: Dict[str, Any], 
                 global_goal: str = ""):
        """
        Initialize a DataSourceAgent.
        
        Args:
            name: Agent identifier
            data: DataFrame containing the dataset
            original_file_path: Path to the original data file
            external_knowledge: Domain knowledge description for this agent
            agent_config: Configuration dictionary for agent behavior
            global_goal: Overall analysis objective
        """
        self.name = name
        self.data = data
        self.external_knowledge = external_knowledge
        self.agent_config = agent_config
        self.original_file_path = original_file_path
        self.global_goal = global_goal

        # Initialize labels and metadata
        self.profile = au.get_enhanced_data_profile(self.data)
        self.importance_label = "Secondary"  # Default value
        self.preliminary_priority = "Medium"
        self.final_priority = "Medium"
        self.summary = ""
        self.insights = []

        # Create agent-specific directory for outputs
        agent_save_path = os.path.join(agent_config['base_savedir'], self.name.replace(' ', '_'))
        os.makedirs(agent_save_path, exist_ok=True)
        
        # Initialize the underlying AgentBase instance
        self.agent_base = AgentBase(
            model_name=agent_config['model_name'],
            savedir=agent_save_path,
            goal=f"Finding trends related to '{global_goal}' in {self.name} dataset",
            verbose=True,
            temperature=agent_config['temperature'],
            n_retries=agent_config['n_retries'],
            api_key=agent_config.get('api_key'),
            base_url=agent_config.get('base_url')
        )
        self.agent_base.set_table(table=self.data, dataset_path=self.original_file_path)
        
        # Initialize utilities
        self.schema_str = au.schema_to_str(self.agent_base.schema)
        self.chat_model = au.get_chat_model(
            agent_config['model_name'],
            agent_config['temperature'],
            api_key=agent_config.get('api_key'),
            base_url=agent_config.get('base_url')
        )
        self.summary = ""
        self.insights = []

    def analyze_self(self) -> Dict[str, Any]:
        """
        Phase 1: Independent analysis. Delegates to InsightWorkflow.
        
        Returns:
            Dictionary containing analysis report
        """
        logger.info(f"[{self.name} Agent]: Starting Phase 1: Independent Analysis...")
        
        try:
            workflow = InsightWorkflow(
                agent_base=self.agent_base,
                branch_depth=self.agent_config.get('branch_depth', 2)
            )
            
            final_state = workflow.run(
                initial_goal=self.agent_base.goal,
                max_questions=self.agent_config.get('max_questions', 2)
            )
            
            self.insights = final_state.get('insights_history', [])
            self.summary = final_state.get('final_summary', 'Analysis completed but no summary generated.')
            
        except Exception as e:
            logger.error(f"[{self.name} Agent]: Independent analysis failed: {e}", exc_info=True)
            self.summary = f"Analysis failed: {e}"
            self.insights = []

        report = {
            "agent_name": self.name,
            "summary": self.summary,
            "key_metrics": self.insights,
            "annotations": [],
        }
        
        logger.info(f"[{self.name} Agent]: Analysis completed. Summary: {self.summary[:100]}...")
        return report

    def annotate_other_agent_summary(
        self, 
        report_to_annotate: Dict[str, Any],
        max_summary_length: int = 1000,
        max_insights_count: int = 3,
        n_retries: int = 2
    ) -> Dict[str, str]:
        """
        Core of background crossover: Generate annotations on another agent's report.
        
        Improved stability features:
        - Input length limiting to prevent token overflow
        - Retry logic for failed attempts
        - Better response parsing with fallback
        
        Args:
            report_to_annotate: Report from another agent to annotate
            max_summary_length: Maximum characters for summary input
            max_insights_count: Maximum number of insights to include
            n_retries: Number of retry attempts on failure
            
        Returns:
            Dictionary containing annotation information
        """
        target_name = report_to_annotate['agent_name']
        
        # Limit input lengths to prevent token overflow
        target_summary = report_to_annotate.get('summary', '')
        if len(target_summary) > max_summary_length:
            target_summary = target_summary[:max_summary_length] + "... [truncated]"
        
        # Limit insights count and convert to string representation
        target_insights = report_to_annotate.get('key_metrics', [])
        if isinstance(target_insights, list) and len(target_insights) > max_insights_count:
            target_insights = target_insights[:max_insights_count]
        
        # Convert insights to safe string representation
        try:
            if isinstance(target_insights, list):
                insights_str = "\n".join([
                    f"- {insight.get('question', 'N/A')}: {insight.get('answer', 'N/A')[:200]}"
                    if isinstance(insight, dict) else str(insight)[:300]
                    for insight in target_insights[:max_insights_count]
                ])
            else:
                insights_str = str(target_insights)[:1000]
        except Exception:
            insights_str = "[Insights unavailable]"
        
        # Also limit schema string
        schema_str_limited = self.schema_str[:1500] if len(self.schema_str) > 1500 else self.schema_str
        
        def _attempt_annotation() -> str:
            """Single annotation attempt."""
            prompt = prompts.ANNOTATION_PROMPT_TEMPLATE.format(
                annotator_name=self.name,
                annotator_knowledge=self.external_knowledge[:500],  # Limit knowledge too
                annotator_schema=schema_str_limited,
                target_agent_name=target_name,
                target_insight=insights_str,
                target_summary=target_summary
            )
            
            response = self.chat_model(prompt)
            comment = response.content if hasattr(response, 'content') else str(response)
            return comment.strip()
        
        def _parse_comment(raw_response: str) -> str:
            """Parse comment from response with fallback."""
            # Try to extract from <comment> tags
            tags = au.extract_html_tags(raw_response, ["comment"])
            if tags and "comment" in tags and tags["comment"]:
                return tags["comment"][0].strip()
            
            # Fallback: use raw response if it looks like valid content
            cleaned = raw_response.strip()
            
            # Filter out meta-responses
            skip_phrases = [
                "no comment", "nothing to add", "no additional", 
                "i don't have", "cannot provide", "unable to"
            ]
            if any(phrase in cleaned.lower() for phrase in skip_phrases):
                return ""
            
            # If response is too short, it's likely not useful
            if len(cleaned) < 10:
                return ""
            
            # Limit output length
            if len(cleaned) > 500:
                cleaned = cleaned[:500] + "..."
            
            return cleaned
        
        # Attempt annotation with retries
        comment = ""
        last_error = None
        
        for attempt in range(n_retries + 1):
            try:
                raw_response = _attempt_annotation()
                comment = _parse_comment(raw_response)
                
                if comment:  # Success
                    logger.debug(f"[{self.name} Agent]: Annotation successful on attempt {attempt + 1}")
                    break
                
            except Exception as e:
                last_error = e
                logger.warning(f"[{self.name} Agent]: Annotation attempt {attempt + 1} failed: {e}")
                
                if attempt < n_retries:
                    # Reduce input size for retry
                    max_summary_length = max_summary_length // 2
                    max_insights_count = max(1, max_insights_count - 1)
                    continue
        
        if not comment and last_error:
            logger.warning(f"[{self.name} Agent]: All annotation attempts failed. Last error: {last_error}")

        return {
            "author_agent": self.name,
            "comment": comment
        }
    
    def get_agent_info(self) -> Dict[str, Any]:
        """
        Get comprehensive information about this agent.
        
        Returns:
            Dictionary with agent metadata
        """
        return {
            "name": self.name,
            "data_shape": self.data.shape,
            "data_columns": list(self.data.columns),
            "preliminary_priority": self.preliminary_priority,
            "final_priority": self.final_priority,
            "importance_label": self.importance_label,
            "file_path": self.original_file_path
        }
