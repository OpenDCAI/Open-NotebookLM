# prompts.py
"""
All prompt templates for the multi-agent analysis system.
All prompts are in English to ensure consistency with LLM models.
"""

# ==============================================================================
# Core Prompt Definitions for Data Annotation and Cross-Analysis
# ==============================================================================

PRELIMINARY_EVAL_PROMPT = """
Role: Data Strategy Consultant
Global Goal: {global_goal}
Current Dataset Metadata (Schema & Stats):
{data_profile}

Task: 
Based ONLY on the schema and statistics provided, evaluate the potential relevance of this dataset to the Global Goal.
Identify if this data contains core KPIs, key dimensions, or is likely just background noise.

Output Format:
Please wrap your evaluation in the following tags:
<relevance>1-10</relevance>
<reasoning>A brief explanation</reasoning>
<priority>High/Medium/Low</priority>
"""

FORMAL_ANNOTATION_PROMPT = """
Role: Chief Data Scientist
Global Goal: {global_goal}
Given the following schema:
<schema>{schema}</schema>
Exploration Summary from the Agent's Deep-Dive:
{exploration_summary}

Task:
Perform a final assessment of this data's importance to the global objective.
Metrics:
- Information Richness (1-10): How deep and high-quality are the insights found?
- Theme Alignment (1-10): How directly does this support the Global Goal?

Decision Criteria:
- "Primary": Contains core metrics; can drive the main analysis.
- "Secondary": Provides context, auxiliary dimensions, or validation.

Output Format:
<richness>1-10</richness>
<alignment>1-10</alignment>
<label>Primary/Secondary</label>
<justification>Detailed reason</justification>
"""

CROSS_QUESTION_PROMPT = """
Role: Cross-domain Analyst
Dataset A (Your Data) Summary: {my_summary}
Dataset B (Target Data) Summary: {other_summary}
Your Label: {my_label}

Task:
Generate analytical questions that require JOINING or COMPARING both datasets to find hidden patterns.
Constraint: 
- If your label is "Primary", generate 3 deep questions.
- If your label is "Secondary", generate 1 focused question.

Output Format:
Generate your questions, each enclosed in <question> tags.
Example: <question>Your question text (Rationale: ...)</question>
"""

# Background annotation prompt
ANNOTATION_PROMPT_TEMPLATE = """
Role: Domain Expert & Critical Reviewer

You are: {annotator_name}
Your Domain Knowledge: {annotator_knowledge}
Your Data Schema: {annotator_schema}

You are reviewing analysis results from another agent.
Target Agent: {target_agent_name}
Target Agent's Analysis Insights: {target_insight}
Target Agent's Analysis Summary: {target_summary}

Task:
Provide critical comments or cross-domain insights based on your expertise.
Focus on:
1. Missing perspectives that your data might provide
2. Potential data quality issues
3. Alternative interpretations
4. Connections to broader business context

If you have no meaningful comments, respond with "no comment".
Otherwise, provide concise but insightful feedback.

Output Format:
<comment>Your critical feedback here</comment>
"""

# # Numerical crossover ideation prompt
# NUMERICAL_CROSSOVER_IDEATION_PROMPT = """
# Role: Senior Data Analyst
# Global Goal: {global_goal}

# Context from all datasets:
# {context}

# Task:
# Based on the analysis summaries and cross-agent annotations above, generate specific, actionable analytical questions that require combining data from multiple datasets.

# Focus on questions that:
# 1. Reveal relationships between different datasets
# 2. Combine metrics from primary and secondary datasets
# 3. Uncover hidden patterns through data joins
# 4. Address the Global Goal through multi-dataset analysis

# Generate 3-5 high-quality analytical questions. Each question should specify which datasets need to be combined.

# Output Format:
# Wrap each question in <question> tags.
# <question>Question 1: Clear description of what to analyze and why (Specify datasets: DatasetA + DatasetB)</question>
# <question>Question 2: ...</question>
# """

# Final synthesis prompt
FINAL_PROMPT_TEMPLATE = """
Role: Senior Business Intelligence Analyst

Context from Complete Multi-Agent Analysis:
{full_context}

Task:
Synthesize all analyses, cross-dataset findings, and agent annotations into a comprehensive final report.

Your output should include:
1. Executive Summary (2-3 paragraphs)
2. Key Insights (bullet points, prioritized by importance)
3. Cross-dataset Discoveries
4. Limitations and Data Quality Notes
5. Recommended Next Steps

Format your response as a JSON object with the following structure:
{{
    "summary": "executive summary text here",
    "insights": ["insight 1", "insight 2", ...],
    "cross_dataset_discoveries": ["discovery 1", ...],
    "limitations": ["limitation 1", ...],
    "next_steps": ["recommendation 1", ...]
}}
"""

# Report generation prompt
REPORT_GENERATION_PROMPT = """
Role: Technical Report Writer

Analysis Workflow Final State:
{state_str}

Task:
Convert this technical workflow state into a professional Markdown report suitable for business stakeholders.
The report should be clear, concise, and focus on actionable insights rather than technical details.

Include:
1. Title and Executive Summary
2. Analysis Methodology Overview
3. Key Findings by Dataset
4. Cross-Dataset Insights
5. Limitations and Assumptions
6. Recommendations
7. Appendices (technical details if necessary)

Format the entire report in Markdown with appropriate headings and structure.
"""

# __all__ = [
#     'PRELIMINARY_EVAL_PROMPT',
#     'FORMAL_ANNOTATION_PROMPT', 
#     'CROSS_QUESTION_PROMPT',
#     'ANNOTATION_PROMPT_TEMPLATE',
#     'NUMERICAL_CROSSOVER_IDEATION_PROMPT',
#     'FINAL_PROMPT_TEMPLATE',
#     'REPORT_GENERATION_PROMPT'
# ]


FINAL_PROMPT_TEMPLATE = """
你是一名首席战略官。你已经收到了来自多个部门的报告，包括他们之间的同行评审（批注），以及一份跨部门的数值交叉分析报告。
你的任务是综合所有这些信息，提炼出 2-5 个高层次的、跨职能的洞察。如果给你的信息中包含了前置内容的一些报错情况，请忽略，不要反映在最终报告中。
请专注于识别单一部门会错过的因果联系、利弊权衡和战略机会。

**完整上下文:**
{full_context}

**指示:**
请生成一个包含两个部分的综合报告：
1. **pred_insights**: 2-5个高层次的洞察，每个洞察应该是一个完整的句子，并包含洞察类型标签（如Trend:, Comparison:, Extreme:, Attribution:等）
2. **pred_summary**: 一个简短的总结段落，概括报告的核心内容

**重要：所有内容（insights 的值、summary）必须用中文撰写。只有 JSON 的 key（如 "insights"、"summary"）和前缀（如 "Trend:"、"Comparison:"）保持英文。**

请使用以下JSON格式输出你的回答：
{{
  "insights": [
    "Trend: 洞察内容1（用中文撰写）",
    "Comparison: 洞察内容2（用中文撰写）", 
    "Extreme: 洞察内容3（用中文撰写）",
    "Attribution: 洞察内容4（用中文撰写）"
  ],
  "summary": "总结内容（用中文撰写）"
}}
"""

# 支持简洁模式和详细模式的最终合成Prompt
FINAL_PROMPT_TEMPLATE_WITH_MODES = """
你是一位**经验丰富的、专注于生成可操作业务报告的资深数据分析师**。

你的任务是：基于提供的所有分析报告、交叉批注、计算结果和背景信息（即 Context），生成一份**最终综合分析报告**。

### 分析内容
{full_context}

### 背景知识（仅供参考，核心结论需基于数据分析）
{background_info}

### 输出模式: {output_mode}

### 输出要求

**如果输出模式是 "concise" (简洁模式):**
1. 每个数据源只保留最重要的 1-2 条洞察
2. 重点突出跨源发现和联合分析结论
3. 总结控制在 500 字以内

**如果输出模式是 "detailed" (详细模式):**
1. 保留所有数据源的完整洞察
2. 包含详细的跨源分析和背景信息关联
3. 在 detailed_appendix 中保存完整的原始报告供参考

### JSON 输出格式
{{
  "insights": [
    "Trend: 洞察1 (关键趋势发现，如时间序列变化、增长/下降趋势)",
    "Comparison: 洞察2 (跨源对比分析，如不同数据源之间的差异、关联)",
    "Extreme: 洞察3 (异常值或极端情况，如最大值、最小值、异常波动)",
    "Attribution: 洞察4 (归因分析，如因果关系、影响因素分析)"
  ],
  "summary": "综合性摘要，概括核心发现和业务含义",
  "detailed_appendix": {{
    "full_reports": ["仅详细模式填充"],
    "crossover_results": ["仅详细模式填充"],
    "background_info": ["仅详细模式填充"]
  }}
}}

**重要要求：**
- **语言要求**：所有内容（insights 的值、summary）必须用**中文**撰写。只有 JSON 的 key（如 "insights"、"summary"）和前缀（如 "Trend:"、"Comparison:"）保持英文。
- insights 列表中的每条洞察必须以 "Trend:"、"Comparison:"、"Extreme:" 或 "Attribution:" 开头，但冒号后的内容必须用中文撰写
- 尽量覆盖所有四种类型，如果某种类型没有相关发现，可以省略
- 每条洞察应该是完整的句子，清晰表达发现
- summary 必须用中文撰写，全面概括核心发现和业务含义

**注意：**
- 如果是简洁模式，detailed_appendix 应为空对象 {{}}
- 如果是详细模式，detailed_appendix 应包含完整信息
- 忽略任何错误信息，只关注有效的分析结果
"""

# 用于背景信息注入的简化模板
BACKGROUND_INFO_SECTION_TEMPLATE = """
--- Background Knowledge (Reference Only) ---
The following background information is provided for context. 

{background_content}

--- End of Background Knowledge ---
"""

FINAL_PROMPT_TEMPLATE_IB = """
你是一位**经验丰富的、专注于生成可操作业务报告的资深数据分析师**。

你的任务是：基于提供的所有分析报告、交叉批注和计算结果（即 Context），生成一份**最终综合分析报告**。

### 输出要求

1.  **内容来源**：严格且仅基于提供的 **Context** 信息进行总结和洞察提取。
2.  **格式要求**：**必须**以 **JSON** 格式输出，并且只包含 **'insights'** 和 **'summary'** 两个顶级键。
3.  **洞察 (insights)**：
    * 必须是**列表 (List)** 形式。
    * 每条洞察应是一个独立的、简洁的**陈述句**。
    * 侧重于**关键发现、异常值或重要趋势**
4.  **总结 (summary)**：
    * 必须是**字符串 (String)** 形式。
    * 内容应是结构化的、详细的**叙述性段落**，全面概述核心发现及其业务含义。

### Context (分析内容和中间结果)
{full_context}

### 最终输出格式 (必须是 JSON,用英文撰写)
{{
  "insights": [
    "第一个关键发现...",
    "第二个关键发现..."
  ],
  "summary": "（详细且结构化的叙述性总结）"
}}
"""


SYNTHESIS_PROMPT_TEMPLATE = """
你是一名首席战略官。你已经收到了来自多个部门的报告，包括他们之间的同行评审（批注），以及一份跨部门的数值交叉分析报告。
你的任务是综合所有这些信息，提炼出 2-5 个高层次的、跨职能的洞察。
请专注于识别单一部门会错过的因果联系、利弊权衡和战略机会。

**完整上下文:**
{full_context}

**指示:**
生成一个最终的洞察列表。每个洞察都应该是一个完整的句子。
请使用 Markdown 的无序列表（以 - 开始）格式化你的回答。
"""

# ### [NEW] ###
# 为数值交叉步骤生成问题的Prompt
NUMERICAL_CROSSOVER_IDEATION_PROMPT = """
你是一位经验丰富的数据分析主管。你已经收到了各个部门的初步分析报告和他们之间的交叉评论（批注）。
你的任务是基于这些信息，提出 1-3 个需要进行**跨数据集数值计算**的具体问题。

这些问题应该是：
1.  **具体的**：可以被转化为代码执行。例如，“比较营销部门的广告支出和销售部门的销售额随时间变化的趋势” 而不是 “看看营销和销售有没有关系”。
2.  **跨领域的**：需要联合至少两个数据源才能回答。
3.  **有价值的**：能够揭示单一部门无法发现的深层联系。

**背景信息:**
{context}

请严格按照以下格式，只输出需要计算的问题，每个问题占一行，不要有其他多余的文字：
<question>问题1</question>
<question>问题2</question>
...
"""

INTERPRET_SOLUTION = """
### Instruction:
You are trying to answer a question based on information provided by a data scientist.

Given the context:
<context>
    You need to answer a question based on information provided by a data scientist.
</context>

Given the following dataset schema:
<schema>{schema}</schema>

Given the goal:
<goal>{goal}</goal>

Given the question:
<question>{question}</question>

Given the analysis:
<analysis>
    <message>
        {message}
    </message>
    {insights}
</analysis>

Instructions:
* Based on the analysis and other information provided above, write an answer to the question enclosed with <question></question> tags.
* **重要：所有内容（answer、insight、justification）必须用中文撰写。**
* The answer should be a single sentence, but it should not be too high level and should include the key details from justification.
* Write your answer in HTML-like tags, enclosing the answer between <answer></answer> tags, followed by a justification between <justification></justification> tags, followed by an insight between <insight></insight> tags.
* Refer to the following example response for the format of the answer and justification.
* The insight should be something interesting and grounded based on the question, goal, and the dataset schema, something that would be interesting. 
* The insight should be as quantiative as possible and informative and non-trivial and concise.
* The insight should be a meaningful conclusion that can be acquired from the analysis in laymans terms

Example response:
<answer>This is a sample answer</answer>
<insight>This is a sample insight</insight>
<justification>This is a sample justification</justification>

### Response:
"""


# ===========================
# (1) Recommend Questions Prompts
# ===========================
def get_question_prompt(method="basic"):
    if method == "basic":
        prompt_template = GET_QUESTIONS_TEMPLATE
        system_template = GET_QUESTIONS_SYSTEM_MESSAGE
    if method == "follow_up":
        prompt_template = FOLLOW_UP_TEMPLATE
        system_template = FOLLOW_UP_SYSTEM_MESSAGE
    if method == "follow_up_with_type":
        prompt_template = FOLLOW_UP_TYPE_TEMPLATE
        system_template = FOLLOW_UP_SYSTEM_MESSAGE

    return prompt_template, system_template


# ===========================
# (2) CODE Prompts
# ===========================

def get_code_prompt(method=None):
    """
    Returns the appropriate prompt template for code generation based on the method.
    """
    code_template = None # Initialize
    
    if method == "single" or method == "basic":
        # 【修改】 指向我们强化的 SINGLE 模板
        code_template = GENERATE_CODE_SINGLE_TEMPLATE
    
    elif method == "multi":
        # 【修改】 指向我们强化的 REINFORCED_MULTI 模板
        code_template = REINFORCED_MULTI_CODE_PROMPT
        
    elif method == "multi_with_paths":
        # 【修改】 指向我们强化的 REINFORCED_MULTI 模板
        code_template = REINFORCED_MULTI_CODE_PROMPT
    
    else:
        # 添加一个后备/默认选项或抛出错误，避免UnboundLocalError
        print(f"Warning: Code prompt method '{method}' not recognized. Falling back to 'single'.")
        # 【修改】 默认也使用强化的 SINGLE 模板
        code_template = GENERATE_CODE_SINGLE_TEMPLATE

    return code_template


# ===========================
# (3) Interpret Prompt
# ===========================

# 在文件顶部，和 INTERPRET_SOLUTION 放在一起
# 我们为多文件场景创建一个新的（或者复用现有的）解释模板
# 这里我们复用 INTERPRET_SOLUTION，因为它足够通用。
# 如果需要更复杂的，可以专门为多文件场景写一个。
INTERPRET_SOLUTION_MULTI = INTERPRET_SOLUTION 

def get_interpret_prompt(method):
    prompt_template = None # 先初始化为 None
    
    if method == "basic":
        prompt_template = INTERPRET_SOLUTION
    
    # 增加对 "interpret" 方法的处理，因为你的 agents.py 可能也用到了这个默认值
    elif method == "interpret":
        prompt_template = INTERPRET_SOLUTION
        
    # 增加对多文件场景的处理，这直接解决了你的 UnboundLocalError
    elif method == "multi_with_paths":
        prompt_template = INTERPRET_SOLUTION_MULTI # 使用多文件解释模板

    # 提供一个健壮的后备选项
    else:
        print(f"Warning: Interpret prompt method '{method}' not recognized. Falling back to 'basic'.")
        prompt_template = INTERPRET_SOLUTION

    return prompt_template
    

# ===========================
# (4) Summarize Insights Prompt
# ===========================
def get_summarize_prompt(method="basic"):
    if method == "basic":
        prompt_template = SUMMARIZE_TEMPLATE
        system_template = SUMMARIZE_SYSTEM_MESSAGE

    return prompt_template, system_template


GET_QUESTIONS_TEMPLATE = """
### Instruction:

Given the following context:
<context>{context}</context>

Given the following goal:
<goal>{goal}</goal>

Given the following schema:
<schema>{schema}</schema>

Instructions:
* Write a list of questions to be solved by the data scientists in your team to explore my data and reach my goal.
* Explore diverse aspects of the data, and ask questions that are relevant to my goal.
* You must ask the right questions to surface anything interesting (trends, anomalies, etc.)
* Make sure these can realistically be answered based on the data schema.
* The insights that your team will extract will be used to generate a report.
* Each question should only have one part, that is a single '?' at the end which only require a single answer.
* Do not number the questions.
* You can produce at most {max_questions} questions. Stop generation after that.
* Most importantly, each question must be enclosed within <question></question> tags. Refer to the example response below:

Example response:
<question>What is the average age of the customers?</question>
<question>What is the distribution of the customers based on their age?</question>

### Response:
"""

GET_QUESTIONS_SYSTEM_MESSAGE = """
You the manager of a data science team whose goal is to help stakeholders within your company extract actionable insights from their data.
You have access to a team of highly skilled data scientists that can answer complex questions about the data.
You call the shots and they do the work.
Your ultimate deliverable is a report that summarizes the findings and makes hypothesis for any trend or anomaly that was found.
"""



RETRY_TEMPLATE = """You failed.

Instructions:
-------------
{initial_prompt}
-------------

Completion:
-------------
{prev_output}
-------------

Above, the Completion did not satisfy the constraints given in the Instructions.
Error:
-------------
{error}
-------------

Please try again. Do not apologize. Please only respond with an answer that satisfies the constraints laid out in the Instructions:

"""


GET_INSIGHTS_TEMPLATE = """
Hi, I require the services of your team to help me reach my goal.

<context>{context}</context>

<goal>{goal}</goal>

<schema>{schema}</schema>

Instructions:
* Produce a list of possible insights that we should look into to explore my data and reach my goal.
* Explore diverse aspects of the data, and present possible interesting insights (with explanation) that are relevant to my goal.
* Make sure these can realistically be based on the data schema.
* The insights that your team will extract will be used to insight a report.
* Each question that you produce must be enclosed in <insight></question> tags.
* Do not number the questions.
* You can produce at most {max_questions} insight.

"""

GET_INSIGHTS_SYSTEM_MESSAGE = """
You the manager of a data science team whose goal is to help stakeholders within your company extract actionable insights from their data.
You have access to a team of highly skilled data scientists that can answer complex questions about the data.
You call the shots and they do the work.
Your ultimate deliverable is a report that summarizes the findings and makes hypothesis for any trend or anomaly that was found.
"""


GET_DATASET_DESCRIPTION_TEMPLATE = """
Hi, I require the services of your team to help me reach my goal.

<context>{context}</context>

<goal>{goal}</goal>

<schema>{schema}</schema>

Instructions:
* Generate a description of the dataset provided in the schema.
* The description should include the number of rows, columns, and a brief summary of the data.
* The description should be enclosed inside <description>content</description> tags.

"""

GET_DATASET_DESCRIPTION_SYSTEM_MESSAGE = """
You the manager of a data science team whose goal is to help stakeholders within your company extract actionable insights from their data.
You have access to a team of highly skilled data scientists that can answer complex questions about the data.
You call the shots and they do the work.
Your ultimate deliverable is a report that summarizes the findings and makes hypothesis for any trend or anomaly that was found.
"""

FOLLOW_UP_TEMPLATE = """
Hi, I require the services of your team to help me reach my goal.

<context>{context}</context>

<goal>{goal}</goal>

<schema>{schema}</schema>

<question>{question}</question>

<answer>{answer}</answer>

Instructions:
* Produce a list of follow up questions explore my data and reach my goal.
* Note that we have already answered <question> and have the answer at <answer>, do not include a question similar to the one above. 
* Explore diverse aspects of the data, and ask questions that are relevant to my goal.
* You must ask the right questions to surface anything interesting (trends, anomalies, etc.)
* Make sure these can realistically be answered based on the data schema.
* The insights that your team will extract will be used to generate a report.
* Each question that you produce must be enclosed in <question>content</question> tags.
* Each question should only have one part, that is a single '?' at the end which only require a single answer.
* Do not number the questions.
* You can produce at most {max_questions} questions.

"""

FOLLOW_UP_TYPE_TEMPLATE = """
Hi, I require the services of your team to help me reach my goal.

<context>{context}</context>

<goal>{goal}</goal>

<schema>{schema}</schema>

<question_type>{question_type}</question_type>

<question>{question}</question>

<answer>{answer}</answer>

Instructions:
* Produce a list of follow up questions explore my data and reach my goal.
* Note that we have already answered <question> and have the answer at <answer>, do not include a question similar to the one above. 
* Explore diverse aspects of the data, and ask questions that are relevant to my goal.
* You must ask the right questions to surface anything interesting (trends, anomalies, etc.)
* Make sure these can realistically be answered based on the data schema.
* The insights that your team will extract will be used to generate a report.
* The question has to adhere to the type of question that is provided in the <question_type> tag
* The type of question is either descriptive, diagnostic, prescriptive, or predictive.
* Each question that you produce must be enclosed in <question>content</question> tags.
* Each question should only have one part, that is a single '?' at the end which only require a single answer.
* Do not number the questions.
* You can produce at most {max_questions} questions.

"""


FOLLOW_UP_SYSTEM_MESSAGE = """
You the manager of a data science team whose goal is to help stakeholders within your company extract actionable insights from their data.
You have access to a team of highly skilled data scientists that can answer complex questions about the data.
You call the shots and they do the work.
Your ultimate deliverable is a report that summarizes the findings and makes hypothesis for any trend or anomaly that was found.
"""

SELECT_A_QUESTION_TEMPLATE = """
Hi, I require the services of your team to help me reach my goal.

<context>{context}</context>

<goal>{goal}</goal>

<prev_questions>{prev_questions_formatted}</prev_questions>

<followup_questions>{followup_questions_formatted}</followup_questions>

Instructions:
* Given a context and a goal, select one follow up question from the above list to explore after prev_question that will help me reach my goal.
* Do not select a question similar to the prev_questions above. 
* Output only the index of the question in your response inside <question_id></question_id> tag.
* The output questions id must be 0-indexed.
"""

SELECT_A_QUESTION_SYSTEM_MESSAGE = """
You the manager of a data science team whose goal is to help stakeholders within your company extract actionable insights from their data.
You have access to a team of highly skilled data scientists that can answer complex questions about the data.
You call the shots and they do the work.
Your ultimate deliverable is a report that summarizes the findings and makes hypothesis for any trend or anomaly that was found.
"""


# 【修改】 这是旧的、较弱的模板。我们同样强化它。
GENERATE_CODE_TEMPLATE = """

Given the goal:\n
{goal}

Given the schema:\n
{schema}

Given the data path:\n
{database_path}

Given the list of predefined functions in insight.tools module and their example usage:\n\n
{function_docs}

Give me the python code required to answer this question "{question}" and put a comment on top of each variable.\n\n

---
**CRITICAL INSTRUCTIONS FOR WRITING PYTHON CODE:**
---
1.  **File Reading**:
    - You MUST load the file at `{database_path}` using the appropriate pandas function **based on its file extension**. 
    - For example: use `pd.read_csv()` for `.csv` files, `pd.read_json()` for `.json` files.
    - **If reading a CSV file**: Handle potential `UnicodeDecodeError`. First, try `encoding='utf-8'`. If it fails, try `encoding='gbk'` or `encoding='latin1'`.

2.  **CRITICAL: Date/Time Columns**:
    - After loading the data, inspect the schema. If you see any columns that represent dates or times (e.g., 'date', 'timestamp'), you **MUST** convert them to datetime objects using `pd.to_datetime(df['column_name'], errors='coerce')`.
    - **DO NOT** use string methods like `.strftime()` before conversion. All date operations **MUST** use the `.dt` accessor *after* conversion.

3.  **Code Quality & Data Types**:
    - When creating a `pd.DataFrame` from a dictionary, ensure all arrays/lists have the same length to avoid `ValueError`.
    - Be mindful of data types. Do not assign string values to numeric columns or vice-versa, to avoid `FutureWarning`.

4.  **Output Generation**:
    - **Chinese Font Setup**: Configure matplotlib for Chinese fonts using:
      ```python
      import matplotlib
      matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS']
      matplotlib.rcParams['axes.unicode_minus'] = False
      ```
    - Make simple plots and save them as `plot.jpg` file.
    - Use standard Python `json` module to save JSON outputs:
      ```python
      with open('filename.json', 'w', encoding='utf-8') as f:
          json.dump(data, f, ensure_ascii=False, indent=2)
      ```
    - For every plot, save a stats json file (`stat.json`), and x/y axis json files (`x_axis.json`, `y_axis.json`).
    - Each json file must have a "name", "description", and "value" field.
---

Make a single code block for starting with ```python
Import json, pandas as pd, and numpy as np at the beginning.
End your code with ```.

Output code:\n
"""

# 【修改】 这是旧的、较弱的多文件模板。我们同样强化它。
GENERATE_CODE_TEMPLATE_MULTI = """

Given the goal:\n
{goal}

Given the schema of the first dataset:\n
{schema}

Given the data path of the first dataset:\n
{database_path}

Given the schema of the second dataset:\n
{user_schema}

Given the data path of the second dataset:\n
{user_database_path}

Given the list of predefined functions in insight.tools module and their example usage:\n\n
{function_docs}

Give me the python code required to answer this question "{question}" and put a comment on top of each variable.\n\n

---
**CRITICAL INSTRUCTIONS FOR WRITING PYTHON CODE:**
---
1.  **File Reading**:
    - You MUST load the files (e.g., `{database_path}`, `{user_database_path}`) using the appropriate pandas function **based on each file's extension**.
    - For example: use `pd.read_csv()` for `.csv` files, `pd.read_json()` for `.json` files.
    - **If reading a CSV file**: Handle potential `UnicodeDecodeError`. First, try `encoding='utf-8'`. If it fails, try `encoding='gbk'` or `encoding='latin1'`.

2.  **CRITICAL: Date/Time Columns**:
    - After loading **EACH** dataframe, inspect its schema. If you see any columns that represent dates or times, you **MUST** convert them to datetime objects using `pd.to_datetime(df['column_name'], errors='coerce')`.
    - **DO NOT** use string methods like `.strftime()` before conversion. All date operations **MUST** use the `.dt` accessor *after* conversion.

3.  **Code Quality & Data Types**:
    - When creating a `pd.DataFrame` from a dictionary, ensure all arrays/lists have the same length to avoid `ValueError`.
    - Be mindful of data types. Do not assign string values to numeric columns or vice-versa, to avoid `FutureWarning`.

4.  **Output Generation**:
    - **Chinese Font Setup**: Configure matplotlib for Chinese fonts using:
      ```python
      import matplotlib
      matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS']
      matplotlib.rcParams['axes.unicode_minus'] = False
      ```
    - You must generate one single simple plot and save it as a `plot.jpg` file.
    - Use standard Python `json` module to save JSON outputs:
      ```python
      with open('filename.json', 'w', encoding='utf-8') as f:
          json.dump(data, f, ensure_ascii=False, indent=2)
      ```
    - For the plot, save a stats json file (`stat.json`), and x/y axis json files (`x_axis.json`, `y_axis.json`).
    - Each json file must have a "name", "description", and "value" field.
---

Make a single code block for starting with ```python
Import json, pandas as pd, and numpy as np at the beginning.
Do not produce code blocks for languages other than Python.
End your code with ```.

Output code:\n
"""

# 【修改】 这是你定义的单文件强化模板。我们应用所有修复。
GENERATE_CODE_SINGLE_TEMPLATE = """
**Goal:** {goal}
**Question:** "{question}"
**Dataset Schema:**
{schema}

**File Path:**
The dataset is located at `{database_path}`.

---
**CRITICAL INSTRUCTIONS FOR WRITING PYTHON CODE:**

1.  **File Reading**:
    - You MUST load the file at `{database_path}` using the appropriate pandas function **based on its file extension** (e.g., `pd.read_csv()`, `pd.read_json()`).
    - **If reading a CSV file**: You MUST handle encoding errors. Use a `try-except` block. First, try `encoding='utf-8'`. If it fails, try `encoding='gbk'` or `encoding='latin1'`.
    - **Example for robust CSV reading**:
      ```python
      import pandas as pd
      file_path = '{database_path}' # This is the path
      try:
          df = pd.read_csv(file_path, encoding='utf-8')
      except UnicodeDecodeError:
          df = pd.read_csv(file_path, encoding='gbk')
      ```

2.  **CRITICAL: Date/Time Columns**:
    - After loading the data, inspect the schema. If you see any columns that represent dates or times (e.g., 'date', 'timestamp'), you **MUST** convert them to datetime objects using `pd.to_datetime(df['column_name'], errors='coerce')`.
    - **DO NOT** attempt to use string methods like `.strftime()` on a column before converting it to datetime. All date operations **MUST** use the `.dt` accessor *after* this conversion.
    - Use `insight.tools.safe_datetime_parse()` for robust date parsing if standard methods fail.

3.  **Code Quality & Data Types**:
    - When creating a `pd.DataFrame` from a dictionary, ensure all arrays/lists have the same length to avoid `ValueError`.
    - Be mindful of data types. Do not assign string values to numeric columns or vice-versa, to avoid `FutureWarning`.
    - Use `insight.tools.safe_numeric_convert()` for converting mixed-type columns to numeric.

4.  **CRITICAL: Empty DataFrame Checks**:
    - After loading data, ALWAYS check if the DataFrame is empty: `if df.empty: print("Warning: Empty DataFrame")`
    - After filtering operations, check if the result is empty before proceeding.
    - Before aggregations (mean, sum, etc.), verify there is data to aggregate.
    - **Example pattern**:
      ```python
      filtered_df = df[df['column'] > threshold]
      if filtered_df.empty:
          print("No data matches the filter criteria")
          # Provide sensible defaults or skip the operation
      else:
          result = filtered_df['value'].mean()
      ```

5.  **Error Handling**:
    - Wrap critical operations in try-except blocks.
    - For column access, verify the column exists first: `if 'column_name' in df.columns:`
    - Handle KeyError, ValueError, and TypeError gracefully.

6.  **Output Generation**:
    - **Chinese Font Setup**: Configure matplotlib for Chinese fonts using:
      ```python
      import matplotlib
      matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS']
      matplotlib.rcParams['axes.unicode_minus'] = False
      ```
    - Use standard Python `json` module to save JSON outputs:
      ```python
      with open('filename.json', 'w', encoding='utf-8') as f:
          json.dump(data, f, ensure_ascii=False, indent=2)
      ```
    - Generate one simple plot and save it as a `.jpg` file.
    - For the plot, save a statistics summary to `stat.json`.
    - Save the X and Y axis data (max 50 points) to `x_axis.json` and `y_axis.json` respectively.
    - Each JSON file must have "name", "description", and "value" fields. Ensure content is less than 4500 characters.

7.  **Code Structure**:
    - Start your code block with ```python and end it with ```.
    - Do not produce any text outside of this single Python code block.

**Available Tools:**
{function_docs}

---
Now, write the Python code to answer the question.

```python
"""

# 【修改】 这是你定义的多文件强化模板。我们应用所有修复。
REINFORCED_MULTI_CODE_PROMPT = """
**Goal:** {goal}
**Question:** "{question}"

**Available Datasets:**
---
**Dataset(s):**
- **Schema:**
{multi_schema}
- **File Path(s):** `{multi_database_path}`
- **Data Profiles (Statistical Summary):**
{multi_profile}
---

**CRITICAL INSTRUCTIONS FOR WRITING PYTHON CODE:**

1.  **File Reading**:
    - You MUST load all files (from `{multi_database_path}`) using the appropriate pandas function **based on their file extension** (e.g., `pd.read_csv()`, `pd.read_json()`).
    - **If reading a CSV file**: You MUST handle encoding errors. Use a `try-except` block for EACH CSV file. First, try `encoding='utf-8'`. If it fails, try `encoding='gbk'` or `encoding='latin1'`.
    - **Example for robust CSV reading** (apply this logic to all CSV files you read):
      ```python
      import pandas as pd
      # For main file (if it's a CSV)
      try:
          df1 = pd.read_csv('/your/csv/path.csv', encoding='utf-8')
      except UnicodeDecodeError:
          df1 = pd.read_csv('/your/csv/path.csv', encoding='gbk')
      ```
    - **For JSON files**: Simply use `df = pd.read_json(file_path)`

2.  **CRITICAL: Date/Time Columns**:
    - After loading **EACH** dataframe, inspect its schema. If a column represents dates/times, you **MUST** convert it to a datetime object using `pd.to_datetime(df['column_name'], errors='coerce')`.
    - **DO NOT** use string methods like `.strftime()` before conversion. All date operations **MUST** use the `.dt` accessor *after* conversion.
    - Use `insight.tools.safe_datetime_parse()` for robust date parsing if standard methods fail.

3.  **Data Merging**:
    - You will likely need to merge or join the dataframes to answer the question. Use `pd.merge()` or `pd.concat()` on a common column (e.g., 'user_id', 'date').
    - **IMPORTANT**: Before merging, verify that the join columns exist in both DataFrames and have compatible types.
    - After merging, check if the result is empty: `if merged_df.empty: print("Warning: No matching records found")`

4.  **CRITICAL: Empty DataFrame Checks**:
    - After loading each file, check if empty: `if df.empty: print(f"Warning: {{filepath}} is empty")`
    - After filtering or merging, always check for empty results.
    - Before aggregations, verify there is data to aggregate.

5.  **Code Quality & Data Types**:
    - When creating a `pd.DataFrame` from a dictionary, ensure all arrays/lists have the same length to avoid `ValueError`.
    - Be mindful of data types. Do not assign string values to numeric columns or vice-versa, to avoid `FutureWarning`.
    - Use `insight.tools.safe_numeric_convert()` for converting mixed-type columns to numeric.

6.  **Error Handling**:
    - Wrap critical operations in try-except blocks.
    - Verify columns exist before accessing them.
    - Handle KeyError, ValueError, and TypeError gracefully.

7.  **Output Generation**:
    - **CRITICAL: Chinese Font Setup**: Before creating any plot, you MUST call `setup()` from `insight.tools` to ensure Chinese characters display correctly in plots. Add this line before any plotting code: `setup()`.
    - Use functions from `insight.tools` to save all outputs.
    - Generate one plot and save it as a `.jpg`.
    - Save statistics to `stat.json`, and axis data (max 100 points) to `x_axis.json` and `y_axis.json`.
    - Call `insight.tools.fix_fnames()` at the very end.

8.  **Code Structure**:
    - Enclose your entire script in a single ```python code block. No other text.

**Available Tools:**
{function_docs}

---
Now, write the Python code to answer the question by analyzing and combining the provided datasets.

```python
"""


def get_g_eval_prompt(method="basic"):
    if method == "basic":
        geval_template, system_template = (
            G_EVAL_BASIC_TEMPLATE,
            G_EVAL_BASIC_SYSTEM_MESSAGE,
        )
    if method == "binary":
        geval_template, system_template = (
            G_EVAL_BINARY_TEMPLATE,
            G_EVAL_BINARY_SYSTEM_MESSAGE,
        )

    return geval_template, system_template


G_EVAL_BASIC_TEMPLATE = """
Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
Provided Answer:
{answer}

Ground Truth Answer:
{gt_answer}

Follow these instructions when writing your response:
* On a scale of 1-10, provide a numerical rating for how close the provided answer is to the ground truth answer, with 10 denoting that the provided answer is the same as ground truth answer.
* Your response should contain only the numerical rating. DONOT include anything else like the provided answer, the ground truth answer, or an explanation of your rating scale in your response.
* Wrap your numerical rating inside <rating></rating> tags.
* Check very carefully before answering.
* Follow the output format as shown in the example below:
Example response:
<rating>7</rating>

### Response:

"""

G_EVAL_BINARY_SYSTEM_MESSAGE = """You are a high school teacher evaluating student responses to a question. You are tasked with grading the response based on how well it answers the question. You are to provide a numerical rating for how well the provided response matches the ground truth answer."""

G_EVAL_BASIC_SYSTEM_MESSAGE = """You are a high school teacher evaluating student responses to a question. You are tasked with grading the response based on how well it answers the question. You are to provide a numerical rating for how well the response answers the question based on the ground truth answer."""


G_EVAL_BINARY_TEMPLATE = """
Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
Provided answer:
{answer}

GT Answer:
{gt_answer}

On a scale of 1-10, provide a numerical rating for how close the provided answer is to the ground truth answer, with 10 denoting that the provided answer is the the same as ground truth answer. The response should contain only the numerical rating.\
    
Check very carefully before answering.

### Response:
"""

G_EVAL_SYSTEM_MESSAGE = """You are a a high school teacher evaluating student responses to a question. You are tasked with grading the response based on how well it answers the question. You are to provide a numerical rating for how well the response answers the question based on the ground truth answer."""


G_EVAL_M2M_TEMPLATE = """
Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
Predicted Answers:
{pred_list}

Grouth Truth Answers:
{gt_list}

For each ground truth answer above, provide the index of the most appropriate predicted answer (1-indexed).
Each line must contain a single integer value denoting the id of the matched prediction.
If there is no appropriate prediction for a ground truth answer, write -1.
Check very carefully before answering.

### Response:
"""

G_EWAL_M2M_SYSTEM_MESSAGE = "You are a high school teacher evaluating student responses to some questions. Before scoring their answers, you need to first match each ground truth answer with the most appropriate answer provided by the student."

SUMMARIZE_TEMPLATE = """
Hi, I require the services of your team to help me reach my goal.

<context>{context}</context>

<goal>{goal}</goal>

<history>{history}</history>

Instructions:
* Given a context and a goal, and all the history of <question_i><answer_i> pairs from the above list generate the 3 top actionable insights.
* Make sure they don't offer actions and the summary should be more about highlights of the findings
* Output each insight within this tag <insight></insight>.
* Each insight should be a meaningful conclusion that can be acquired from the analysis in laymans terms and should be as quantiative as possible and should aggregate the findings.
"""

SUMMARIZE_SYSTEM_MESSAGE = """
You the manager of a data science team whose goal is to help stakeholders within your company extract actionable insights from their data.
You have access to a team of highly skilled data scientists that can answer complex questions about the data.
You call the shots and they do the work.
Your ultimate deliverable is a report that summarizes the findings and makes hypothesis for any trend or anomaly that was found.
"""

# --- 在 prompts/__init__.py 的顶部或合适位置，添加这个新的模板 ---

# 新增的Prompt模板，用于指导LLM处理多个文件路径
MULTI_WITH_PATHS_CODE_PROMPT = """
Your goal is to write a Python script that addresses the following question.

**Overall Goal:**
{goal}

**Current Question:**
{question}

You have access to multiple datasets. Here are their schemas and file paths:

<schemas>
{schema}
</schemas>

**Important Instructions:**
1.  You **MUST** write a Python script.
2.  Load the necessary data from the provided CSV file paths. You might need to load and merge data from multiple files.
3.  The main dataset is located at `{database_path}`. Other datasets are listed in the schema section.
4.  **CRITICAL: Chinese Font Setup**: Before creating any plot, you MUST call `setup()` from `insight.tools` to ensure Chinese characters display correctly in plots. Add this line before any plotting code: `setup()`.
5.  Use the `tools` module for plotting and saving results. All outputs **MUST** be saved to files using the provided functions.
6.  **Do not** use `plt.show()` or `print()` for final outputs. Save plots as `plot.jpg` and statistical results as JSON files (`stat.json`, `x_axis.json`, `y_axis.json`).
7.  The final script should be enclosed in a single ```python code block.

Available tools from the `tools` module:
{function_docs}

Begin writing the Python script now.
```python
"""

REPORT_GENERATION_PROMPT = """
You are a professional data scientist and report writer. Your task is to generate a comprehensive academic data analysis report in **Markdown** format based on the conversation history provided.

### Requirements:
1. **Language**: The entire report must be written in **English**.
2. **Content Filtering**: 
   - Focus ONLY on the successful analysis steps, logic, and results.
   - **DO NOT** include any code errors, debugging processes, or failed attempts that appeared in the chat history.
3. **Image Insertion**: 
   - You must include the visualizations generated during the analysis. 
   - Insert them using Markdown syntax: `![Figure Description](path/to/figure.png)`.
   - Use the figure paths provided in the context.
4. **Formatting**: Use clear headers (H1, H2, H3), bullet points, and tables to organize the content.

### Report Structure:
1. **Title**: A concise title for the analysis.
2. **Abstract**: (approx. 200 words) Background, dataset summary, methods, and key conclusions.
3. **Introduction**: Background of the task and dataset description.
4. **Methodology**:
    - **Dataset**: Statistical description, feature analysis, missing values, etc.
    - **Data Processing**: Steps taken to clean and process the data (show processed data examples if available).
    - **Modeling/Analysis**: Algorithms or analytical methods used.
5. **Results**: 
    - Present key findings.
    - **Crucial**: Insert the generated figures here to support your analysis.
    - Use tables to summarize model metrics or key data statistics.
6. **Conclusion**: (approx. 200 words) Summary of the entire report.

### Context:
The chat history involves a user interacting with a code interpreter to analyze data. Your job is to synthesize this interaction into a formal report.

Here's the state data: {state_str}

Please generate a detailed report based on data and requirements above.
"""