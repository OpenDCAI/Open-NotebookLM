# insight_discovery.py
"""
Main API for multi-dataset insight discovery system.
Provides high-level interfaces for both folder-based and single-dataset analysis.

Now supports:
- Non-tabular data handling (txt, images)
- Background knowledge collection and injection
- Concise/Detailed output modes
"""

import os
import json
import pandas as pd
from typing import List, Tuple, Dict, Any, Optional, Union

from dm_components.config import logger
from dm_components.agents.datasource_agent import DataSourceAgent
from dm_components.utils.dataloader_utils import DataSourceReader
from dm_components.workflows.orches_workflow import OrchestratorWorkflow


# Type alias for background text data
BackgroundTextData = Dict[str, Any]


class InsightEntry:
    """
    Main interface for automated insight discovery across datasets.
    
    This class provides two primary modes of operation:
    1. analyze_folder(): Analyze all datasets in a folder (with meta-info.json support)
    2. analyze_single_dataset(): Analyze one or two specific datasets
    
    New features:
    - Handles non-tabular data (txt, images) as background knowledge
    - Supports output_mode: "concise" or "detailed"
    - Collects and injects background information into final synthesis
    
    Both methods return a tuple of (insights_list, summary_string) or
    (insights_list, summary_string, detailed_appendix) in detailed mode.
    """
    
    def __init__(self, 
                 model_name: str = "gpt-4.1-nano",
                 base_savedir: str = "./outputs",
                 temperature: float = 0.1,
                 n_retries: int = 1,
                 branch_depth: int = 1,
                 max_questions: int = 1,
                 text_summary_threshold: int = 2000,
                 default_output_mode: str = "concise",
                 api_key: str = "",
                 base_url: str = ""):
        """
        Initialize the insight discovery system.
        
        Args:
            model_name: LLM model to use for analysis
            base_savedir: Base directory for saving outputs
            temperature: LLM temperature (0.0-1.0)
            n_retries: Number of retries for failed LLM calls
            branch_depth: Exploration depth for single-dataset analysis
            max_questions: Max questions per iteration
            text_summary_threshold: Character threshold for text summarization (NEW)
            default_output_mode: Default output mode - "concise" or "detailed" (NEW)
            api_key: API key for LLM (NEW)
            base_url: Base URL for LLM API (NEW)
        """
        self.model_name = model_name
        self.base_savedir = base_savedir
        self.temperature = temperature
        self.n_retries = n_retries
        self.branch_depth = branch_depth
        self.max_questions = max_questions
        self.text_summary_threshold = text_summary_threshold
        self.default_output_mode = default_output_mode
        self.api_key = api_key
        self.base_url = base_url
        
        # Set global API config for all downstream functions
        from dm_components.utils import agent_utils as au
        au.set_global_api_config(api_key=api_key, base_url=base_url)
        
        # Background knowledge pool for non-tabular data
        self.background_knowledge_pool: List[BackgroundTextData] = []
        
        # Ensure output directory exists
        os.makedirs(self.base_savedir, exist_ok=True)
        
        logger.info(f"InsightEntry initialized with model={model_name}, "
                   f"output_dir={base_savedir}, output_mode={default_output_mode}")
    
    def _get_agent_config(self) -> Dict[str, Any]:
        """Get unified agent configuration."""
        return {
            "model_name": self.model_name,
            "base_savedir": self.base_savedir,
            "temperature": self.temperature,
            "n_retries": self.n_retries,
            "branch_depth": self.branch_depth,
            "max_questions": self.max_questions,
            "api_key": self.api_key,
            "base_url": self.base_url
        }
    
    def _create_agent_from_dataframe(self, 
                                    name: str, 
                                    dataframe: pd.DataFrame, 
                                    file_path: str,
                                    description: str) -> Optional[DataSourceAgent]:
        """
        Create a DataSourceAgent from a DataFrame.
        
        Args:
            name: Agent name
            dataframe: Data to analyze
            file_path: Original file path
            description: Data source description
            
        Returns:
            DataSourceAgent instance or None if creation fails
        """
        try:
            external_knowledge = (
                f"An expert analyst in {name} domain. "
                f"Data source: {description}"
            )
            
            agent = DataSourceAgent(
                name=name,
                data=dataframe,
                original_file_path=file_path,
                external_knowledge=external_knowledge,
                agent_config=self._get_agent_config(),
                global_goal=""  # Will be set by workflow
            )
            
            logger.info(f"Created agent [{name}] with {len(dataframe)} rows")
            return agent
            
        except Exception as e:
            logger.error(f"Failed to create agent {name}: {e}")
            return None
    
    def _read_meta_config(self, data_folder: str) -> Dict[str, Any]:
        """
        Read meta.json configuration from parent directory.
        
        Args:
            data_folder: Data folder path
            
        Returns:
            Meta configuration dictionary
        """
        parent_dir = os.path.dirname(data_folder)
        meta_path = os.path.join(parent_dir, "meta-info.json")
        
        if not os.path.exists(meta_path):
            logger.info(f"No meta-info.json found at {meta_path}")
            return {}
        
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta_data = json.load(f)
            
            logger.info(f"Loaded meta.json: goal='{meta_data.get('goal', 'unspecified')}'")
            return meta_data
            
        except Exception as e:
            logger.error(f"Failed to read meta-info.json: {e}")
            return {}
    
    def _process_single_file(
        self, 
        file_path: str, 
        processed_dir: str,
        include_background: bool = True
    ) -> Tuple[List[DataSourceAgent], List[BackgroundTextData]]:
        """
        Process a single data file and create appropriate agents.
        
        Now handles non-tabular data (txt, images) as background knowledge.
        
        Args:
            file_path: Path to data file
            processed_dir: Directory for processed files
            include_background: Whether to collect non-tabular data as background
            
        Returns:
            Tuple of (list of created agents, list of background info dicts)
        """
        agents = []
        background_info = []
        filename = os.path.basename(file_path)
        
        try:
            # Read data using enhanced DataSourceReader
            loaded_data = DataSourceReader.read_data(
                file_path,
                as_background=False,  # Try structured first
                max_chars_for_direct_use=self.text_summary_threshold
            )
            
            # Check if it's background text data (non-tabular)
            if isinstance(loaded_data, dict) and loaded_data.get('type') == 'background_text':
                # This is non-tabular data (txt or chart image)
                if include_background:
                    logger.info(f"Collected background info from: {filename}")
                    background_info.append(loaded_data)
                else:
                    logger.info(f"Skipping background data (include_background=False): {filename}")
                return agents, background_info
            
            if isinstance(loaded_data, dict) and 'type' not in loaded_data:
                # Multi-table file (e.g., SQLite) - dict of DataFrames
                logger.info(f"Processing multi-table file: {filename}")
                file_basename = os.path.splitext(filename)[0]
                
                for table_name, table_df in loaded_data.items():
                    if not isinstance(table_df, pd.DataFrame):
                        continue
                        
                    csv_name = f"{file_basename}_{table_name}.csv"
                    processed_file_path = os.path.join(processed_dir, csv_name)
                    table_df.to_csv(processed_file_path, index=False)
                    
                    agent_name = f"{file_basename}-{table_name}"
                    description = f"Table {table_name} in {filename}"
                    agent = self._create_agent_from_dataframe(
                        agent_name, table_df, processed_file_path, description
                    )
                    if agent:
                        agents.append(agent)
                        
            elif isinstance(loaded_data, pd.DataFrame):
                # Single-table file
                logger.info(f"Processing single-table file: {filename}")
                file_basename = os.path.splitext(filename)[0]
                csv_name = f"{file_basename}.csv"
                processed_file_path = os.path.join(processed_dir, csv_name)
                loaded_data.to_csv(processed_file_path, index=False)

                description = f"File {filename}"
                agent = self._create_agent_from_dataframe(
                    file_basename, loaded_data, processed_file_path, description
                )
                if agent:
                    agents.append(agent)
                    
            else:
                logger.warning(f"Unknown data type from {filename}: {type(loaded_data)}")
                
        except Exception as e:
            logger.error(f"Failed to process file {filename}: {e}")
            
        return agents, background_info
    
    def analyze_folder(
        self, 
        data_folder: str,
        use_meta_goal: bool = True,
        output_mode: Optional[str] = None,
        include_background: bool = True
    ) -> Union[Tuple[List[str], str], Tuple[List[str], str, Dict[str, Any]]]:
        """
        Analyze all datasets in a folder.
        
        Now supports:
        - Non-tabular data (txt, images) as background knowledge
        - Concise/Detailed output modes
        
        Args:
            data_folder: Path to folder containing data files
            use_meta_goal: Whether to use goal from meta-info.json
            output_mode: "concise" or "detailed" (defaults to self.default_output_mode)
            include_background: Whether to process non-tabular data as background
            
        Returns:
            Tuple of (insights, summary) in concise mode, or
            Tuple of (insights, summary, detailed_appendix) in detailed mode
        """
        logger.info(f"Analyzing data folder: {data_folder}")
        
        # Use default output mode if not specified
        output_mode = output_mode or self.default_output_mode
        
        # Validate folder
        if not os.path.exists(data_folder):
            logger.error(f"Data folder not found: {data_folder}")
            return {
                "synthesized_insights": [],
                "raw_insights": [],
                "summary": f"Data folder not found: {data_folder}",
                "detailed_appendix": {}
            }
        
        # Read meta configuration
        meta_data = self._read_meta_config(data_folder) if use_meta_goal else {}
        global_goal = meta_data.get('goal', 'Discover insights from multiple datasets')
        
        processed_dir = os.path.join(data_folder, "processed")
        os.makedirs(processed_dir, exist_ok=True)

        # Process all files - collect agents and background info
        all_agents = []
        all_background_info = []
        
        for filename in os.listdir(data_folder):
            file_path = os.path.join(data_folder, filename)
            
            if os.path.isdir(file_path):  # 跳过目录
                continue

            agents, background_items = self._process_single_file(
                file_path, 
                processed_dir,
                include_background=include_background
            )
            all_agents.extend(agents)
            all_background_info.extend(background_items)
        
        # Store background info for reference
        self.background_knowledge_pool = all_background_info
        
        # Check if any agents were created
        if not all_agents:
            # If we have background info but no agents, provide a warning
            if all_background_info:
                logger.warning("No tabular data found, but collected background info. "
                             "Analysis requires at least one tabular data source.")
            logger.error("No data agents were successfully created")
            return {
                "synthesized_insights": [],
                "raw_insights": [],
                "summary": "No analyzable data found",
                "detailed_appendix": {}
            }
        
        logger.info(f"Created {len(all_agents)} agents from {data_folder}")
        if all_background_info:
            logger.info(f"Collected {len(all_background_info)} background knowledge items")
        
        # Run multi-agent analysis
        try:
            workflow = OrchestratorWorkflow(
                data_agents=all_agents,
                global_goal=global_goal
            )
            
            # Run with background info and output mode
            result = workflow.run(
                output_mode=output_mode,
                background_knowledge_pool=all_background_info
            )
            
            # result is now a dictionary with keys: synthesized_insights, raw_insights, summary, detailed_appendix
            insights = result.get("synthesized_insights", [])
            raw_insights = result.get("raw_insights", [])
            summary = result.get("summary", "")
            detailed_appendix = result.get("detailed_appendix", {})
            
            logger.info(f"Analysis completed: {len(insights)} synthesized insights, {len(raw_insights)} raw insights (mode: {output_mode})")
            
            # Return the full result dictionary
            return result
            
        except Exception as e:
            logger.error(f"Multi-agent analysis failed: {e}", exc_info=True)
            # Return dictionary format for consistency
            return {
                "synthesized_insights": [],
                "raw_insights": [],
                "summary": f"Analysis failed: {str(e)}",
                "detailed_appendix": {}
            }
    


    def analyze_insight_bench(self, dataset_csv_path: str, user_dataset_csv_path: Optional[str] = None, **kwargs) -> Tuple[List[str], str]:
        """
        分析单个数据集 (可能包含用户数据集) 并返回洞察。
        这个方法模仿 analyze_folder 的内部逻辑，但只处理传入的 CSV 文件路径。
        
        Args:
            dataset_csv_path: 核心数据集的 CSV 路径
            user_dataset_csv_path: 用户提供的数据集的 CSV 路径 (可选)
            **kwargs: 允许传入 max_questions, branch_depth 等用于覆盖 Agent 配置的参数
            
        Returns:
            Tuple[pred_insights, pred_summary]: 洞察列表和总结
        """
        all_agents: List[DataSourceAgent] = []
        
        # 临时更新 agent_config 以接受 exp_dict 中的参数覆盖
        current_config = self.agent_config.copy()
        current_config.update(kwargs)
        
        
        def _create_single_agent_from_path(file_path: str, agent_suffix: str, source_description: str):
            """内部辅助函数：从路径读取数据并创建 Agent"""
            try:
                # 1. 读取数据
                loaded_data = DataSourceReader.read_data(file_path)
                if not isinstance(loaded_data, pd.DataFrame):
                    logger.warning(f"文件 {os.path.basename(file_path)} 返回了非 DataFrame 数据，跳过。")
                    return
                
                # 2. 创建 Agent
                agent_name = agent_suffix.replace('_', ' ').strip().title()
                # 外部知识可以定义 Agent 的角色和数据来源
                external_knowledge = f"一名 {agent_name} 领域的专家分析师。数据来源: {source_description}"
                
                agent = DataSourceAgent(
                    name=agent_name,
                    data=loaded_data,
                    original_file_path=file_path,
                    external_knowledge=external_knowledge,
                    agent_config=current_config # 使用更新后的配置
                )
                all_agents.append(agent)
                logger.info(f"成功创建 Agent: [{agent_name}] (文件: {os.path.basename(file_path)})")
            except Exception as e:
                logger.error(f"处理文件 {os.path.basename(file_path)} 时发生意外错误: {e}")


        # 1. 处理核心数据集
        _create_single_agent_from_path(
            file_path=dataset_csv_path,
            agent_suffix="Core Dataset",
            source_description=f"核心数据集文件: {os.path.basename(dataset_csv_path)}"
        )

        # 2. 处理用户数据集 (如果存在)
        if user_dataset_csv_path and os.path.exists(user_dataset_csv_path):
            _create_single_agent_from_path(
                file_path=user_dataset_csv_path,
                agent_suffix="User Dataset",
                source_description=f"用户提供的数据集文件: {os.path.basename(user_dataset_csv_path)}"
            )

        if not all_agents:
            logger.error(f"未能成功加载数据集 {os.path.basename(dataset_csv_path)} 的任何 Agent。")
            return {
                "synthesized_insights": [],
                "raw_insights": [],
                "summary": "没有可分析的数据",
                "detailed_appendix": {}
            }

        # 3. 运行工作流 (与 analyze_folder 相同)
        logger.info("===== 运行单个数据集分析工作流 =====")
        workflow = OrchestratorWorkflow(data_agents=all_agents)
        result = workflow.run()
        
        # Return the full result dictionary
        return result
