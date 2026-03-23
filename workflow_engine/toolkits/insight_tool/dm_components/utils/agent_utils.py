import os
import numpy as np, pandas as pd, re, json, os, shutil, inspect
import nbformat
import contextlib
import io
import os
import re
import subprocess
import traceback
import sys

from io import StringIO
from pathlib import Path
from dm_components import prompts
from copy import deepcopy
from typing import Dict, Any, List
from dm_components import tools
from dateutil.parser import parse
from langchain.schema import HumanMessage, SystemMessage
from warnings import warn
from functools import partial
from langchain.prompts import PromptTemplate
from openai import OpenAI
from pathlib import Path
import httpx

# from langchain_community.chat_models import ChatOpenAI


OPENAI_API_KEY = os.getenv("QDF_API_KEY")
OPENAI_API_URL = os.getenv("QDF_API_URL")

# Global config for API credentials (set by InsightEntry)
_global_api_key = None
_global_base_url = None

def set_global_api_config(api_key: str = None, base_url: str = None):
    """Set global API configuration for all get_chat_model calls."""
    global _global_api_key, _global_base_url
    if api_key:
        _global_api_key = api_key
    if base_url:
        _global_base_url = base_url
JSON_MAX_TOKENS = 40000
JSON_MAX_CHARS = JSON_MAX_TOKENS * 4  # 4 chars per token (roughly)


def interpret_solution(
    solution: dict,
    n_retries: int,
    model_name: str,
    prompt_method,
    schema,
    temperature: 0,
) -> str:
    """
    Produce insights for a task based on a solution output by a model

    Parameters:
    -----------
    solution: dict
        The output of the code generation function
    answer_template: dict
        A template for the answer that the human should provide. This template should contain a "results" tag
        that contains a list of expected results in the form of dictionaries. Each dictionary should contain
        the following keys: "name", "description", and "value". The model will be asked to fill in the values.
    model: str
        The name of the model to use (default: gpt-4)
    n_retries: int
        The number of times to retry the interpretation if it fails

    Returns:
    --------
    solution_path: str
        The path to the input solution file, which has been updated with the interpretation

    """
    prompt_template = prompts.get_interpret_prompt(method=prompt_method)
    # create prompt
    prompt = PromptTemplate.from_template(prompt_template)

    insight_prompt = _build_insight_prompt(solution)

    # instantiate llm model
    llm = get_chat_model(model_name, temperature)

    # Get human readable answer
    out, _ = retry_on_parsing_error(
        llm,
        prompt.format(
            goal=solution["goal"],
            question=solution["question"],
            message=solution["code_output"],
            insights=insight_prompt,
            schema=schema,
        ),
        parser=_parse_human_readable_insight,
        n_retries=n_retries,
    )
    solution["interpretation"] = out
    return solution


def extract_python_code_blocks(text):
    """
    Extract and merge Python code blocks from a given text string.

    The function identifies code blocks that start with ``` or ```python and end with ```.
    After extracting the code blocks, it removes the start and end delimiters (```, ```python),
    and merges the code blocks together into a single string.

    Parameters
    ----------
    text : str
        The input string from which Python code blocks need to be extracted.

    Returns
    -------
    str
        A string containing the merged Python code blocks stripped of leading and trailing whitespaces.
        Code blocks are separated by a newline character.

    """

    code_blocks = re.findall(r"```(?:python)?(.*?)```", text, re.DOTALL)
    return "\n".join(block.strip() for block in code_blocks)


class PythonREPL:
    """
    Simulates a standalone Python REPL.

    TODO add a way to pass a random seed to the REPL
    """

    def __init__(self):
        self.history = []

    def run(self, command: str, workdir: str = None) -> str:
        """Run command with own globals/locals and returns anything printed."""

        if workdir is not None:
            old_cwd = Path.cwd()
            os.chdir(workdir)

        # 1. 定义一个所有代码执行前都需要的 "Header"
        # 这可以防止 LLM 忘记导入常用库
        REPL_HEADER = """
import pandas as pd
import numpy as np
import os
import sys
import json
import warnings
warnings.filterwarnings('ignore')

# Try to setup Chinese font for matplotlib (optional)
try:
    import matplotlib
    matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS', 'sans-serif']
    matplotlib.rcParams['axes.unicode_minus'] = False
except Exception:
    pass
"""

        # 2. Dynamically add project root to sys.path
        # Path calculation: agent_utils.py is at insight_tool/dm_components/utils/agent_utils.py
        # Need to go up 5 levels to reach Open-NotebookLM root
        src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..'))
        
        # 3. 组合 Header、路径修复 和 LLM 生成的代码
        full_command = f"""
{REPL_HEADER}
if '{src_dir}' not in sys.path:
    sys.path.insert(0, '{src_dir}')

# --- LLM Generated Code Below ---
{command}
"""

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            try:
                # Dynamically add project root to sys.path
                # This allows the REPL environment to find 'insight' package
                src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..'))
                exec(f"import sys\nif '{src_dir}' not in sys.path:\n    sys.path.insert(0, '{src_dir}')", locals())
                
                exec(full_command, locals())
                valid = True
                retry_message = ""
                self.history.append((command, workdir))
            except Exception as e:
                valid = False
                retry_message = traceback.format_exc() + "\n" + str(e)
            finally:
                if workdir is not None:
                    os.chdir(old_cwd)
        output = buffer.getvalue()

        return output, valid, retry_message

    def clone(self):
        """Clone the REPL from history.

        it is not possible to clone the REPL from the globals/locals because they
        may contain references to objects that cannot be pickled e.g. python modules.
        Instead, we clone the REPL by replaying the history.

        Python REPL类中的clone()方法是为了复制当前REPL的状态。
        由于REPL类内部维护了一个历史记录（history），该历史记录包含了之前执行过的所有命令以及执行时的工作目录。
        clone()方法通过创建一个新的REPL实例，并深拷贝历史记录，然后重新执行历史记录中的所有命令来复制当前REPL的状态。
        """
        new_repl = PythonREPL()
        # deepcopy of history
        new_repl.history = deepcopy(self.history)

        for command, workdir in self.history:
            new_repl.run(command, workdir=workdir)

        return new_repl


def _execute_command(args):
    """Execute a command and return the stdout, stderr and return code

    Parameters
    ----------
    args : list of str or str, directly passed to subprocess.Popen

    Returns
    -------
    stdout : str
        stdout of the command
    stderr : str
        stderr of the command
    returncode : int
        return code of the command
    """
    try:
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False
        )
    except FileNotFoundError as e:
        return "", str(e), 1

    stdout, stderr = process.communicate()

    # decode bytes object to string
    stdout = stdout.decode("utf-8")
    stderr = stderr.decode("utf-8")

    return stdout, stderr, process.returncode


def pip_install(requirements):
    """Install a list of requirements using pip

    Parameters
    ----------
    requirements : list of str
        List of requirements to install, should be in the format of pip install <requirement>

    Returns
    -------
    stdout : str
        stdout of the command
    valid : bool
        True if the installation was successful, False otherwise
    retry_message : str
        Error message if the installation was not successful
    """

    if isinstance(requirements, str):
        requirements = [requirements]
    retry_messages = []
    stdouts = []
    for req in requirements:
        stdout, stderr, code = _execute_command(["pip", "install", req])
        stdouts.append(stdout)
        if stdout.strip().startswith("Usage:"):
            retry_messages.append(
                f"Seems like there is an error on the pip commandline, it just prints usage. stderr:\n{stderr}. stdout:\n{stdout[-1000:]}"
            )
        if code != 0:
            retry_messages.append(
                f"Error code {code} when installing {req}. stderr:\n{stderr}. stdout:\n{stdout[-1000:]}"
            )

    valid = len(retry_messages) == 0
    retry_message = "\n".join(retry_messages)
    return "\n".join(stdouts), valid, retry_message


# =============================================================================
# Code generation
# =============================================================================
def _code_parser(code, output_folder):
    """
    A parser that is used to parse the code generated by the LLM
    and determine whether it is acceptable or not

    """
    # Clean output folder
    output_folder = Path(output_folder)
    if output_folder.exists():
        shutil.rmtree(output_folder)
    output_folder.mkdir(parents=True)

    # Extract code blocks from the input code (might contain other text)
    code_block = extract_python_code_blocks(code)
    if len(code_block) == 0:
        # No code blocks detected so input is likely already raw code
        code_block = code

    # Run code and report any errors
    output, valid, retry_message = PythonREPL().run(code_block, workdir=output_folder)
    if not valid:
        return "", valid, retry_message

    # Validate output files
    json_files = [f.name for f in output_folder.glob("*.json")]
    plot_files = [f.name for f in output_folder.glob("*.jpg")]

    try:
        # assert that there is x_axis.json, y_axis.json, and stat.json in json_files
        assert "x_axis.json" in json_files
        assert "y_axis.json" in json_files
        assert "stat.json" in json_files
        assert len(json_files) == 3

        # Check that the total length of all json files is not too long
        json_lengths = [len(open(output_folder / f).read()) for f in json_files]
        total_json_chars = sum(json_lengths)
        if total_json_chars > JSON_MAX_CHARS:
            return (
                "",
                False,
                f"Error: The total length of your json files cannot exceed {JSON_MAX_CHARS} characters. Here is the total length of each json file: {', '.join(f'{f} ({l} characters)' for f, l in zip(json_files, json_lengths))}.",
            )

        assert len(plot_files) == 1 and "plot.jpg" in plot_files

    except:
        return (
            "",
            False,
            f"Error: Your code did not generate the expected output files. Expected x_axis.json, y_axis.json, and stat.json files.",
        )

    # All checks have passed!
    return output, True, ""


def retry_on_parsing_error(
    llm,
    initial_prompt,
    parser,
    n_retries,
    exception_on_max_retries=True,
):
    """
    Try querying a LLM until it returns a valid value with a maximum number of retries.

    Parameters:
    -----------
    llm : callable
        A langchain LLM model.
    initial_prompt : str
        The initial prompt to send to the LLM.
    parser : callable
        A function taking a message and returning a tuple (value, valid, retry_message),
        where retries will be made until valid is True.
    n_retries : int
        The maximum number of retries.
    exception_on_max_retries : bool
        If True, raise an exception if the maximum number of retries is reached.
        Otherwise, returns "".

    Returns:
    --------
    value : str
        The value returned by the LLM.
    completions : list
        The attempts made by the LLM.

    """
    retry_template = prompts.RETRY_TEMPLATE
    prompt = initial_prompt

    completions = []
    for i in range(n_retries + 1):  # Add one since the initial prompt is not a retry
        # Try to get a valid completion
        completions.append(llm(prompt))
        output, valid, retry_message = parser(completions[-1])

        # If parser execution succeeds return the output
        if valid:
            return output, completions

        # If parser execution fails, produce a new prompt that includes the previous output and the error message
        warn(
            f"Retry {i+1}/{n_retries} - Query failed with error: {retry_message}",
            RuntimeWarning,
        )
        prompt = retry_template.format(
            initial_prompt=initial_prompt,
            prev_output=completions[-1],
            error=retry_message,
        )

    if exception_on_max_retries:
        return f"Could not parse a valid value after {n_retries} retries.", [
            "```python\nimport pandas as pd```",
            "```python\nimport numpy as np```",
        ]
    else:
        return retry_message, completions


def _extract_top_values(values, k=5, max_str_len=100):
    """
    Extracts the top k values from a pandas series

    Parameters
    ----------
    values : pandas.Series
        Series to extract top values from
    k : int, optional
        Number of top values to extract, by default 5
    max_str_len : int, optional
        Maximum length of string values (will be truncated), by default 100

    """
    top = values.value_counts().iloc[:k].index.values.tolist()
    top = [x if not isinstance(x, str) else x[:max_str_len] for x in top]
    return top


def get_schema(df):
    """
    Extracts schema from a pandas dataframe

    Parameters
    ----------
    df : pandas.DataFrame
        Dataframe to extract schema from

    Returns
    -------
    list of dict
        Schema for each column in the dataframe

    """
    schema = []

    for col in df.columns:
        info = {
            "name": col,
            "type": df[col].dtype,
            "missing_count": df[col].isna().sum(),
            "unique_count": df[col].unique().shape[0],
        }

        # If the column is numeric, extract some stats
        if np.issubdtype(df[col].dtype, np.number):
            info["min"] = df[col].min()
            info["max"] = df[col].max()
            info["mean"] = df[col].mean()
            info["std"] = df[col].std()
        # If the column is a date, extract the min and max
        elif _is_date(df[col].iloc[0]):
            info["min"] = df[col].dropna().min()
            info["max"] = df[col].dropna().max()
        # If the column is something else, extract the top values
        else:
            info["top5_unique_values"] = _extract_top_values(df[col])

        schema.append(info)

    return schema


def schema_to_str(schema) -> str:
    """Converts the list of dict to a promptable string.

    Parameters
    ----------
    schema : list of dict
        Schema for each column in the dataframe

    Returns
    -------
    str
        String representation of the schema
    """
    schema_str = ""
    for col in schema:
        schema_str += f"Column: {col['name']} ({col['type']})\n"
        for key, val in col.items():
            if key in ["name", "type"]:
                continue
            schema_str += f"  {key}: {val}\n"
    return schema_str


def _is_date(string):
    """
    Checks if a string is a date

    Parameters
    ----------
    string : str
        String to check

    Returns
    -------
    bool
        True if the string is a date, False otherwise

    """
    try:
        parse(str(string))
        return True
    except ValueError:
        return False


def schema_to_str(schema) -> str:
    """Converts the list of dict to a promptable string.

    Parameters
    ----------
    schema : list of dict
        Schema for each column in the dataframe

    Returns
    -------
    str
        String representation of the schema
    """
    schema_str = ""
    for col in schema:
        schema_str += f"Column: {col['name']} ({col['type']})\n"
        for key, val in col.items():
            if key in ["name", "type"]:
                continue
            schema_str += f"  {key}: {val}\n"
    return schema_str


def convert_messages_to_text(messages):
    """
    Convert a list of messages to a string

    Parameters
    ----------
    messages : list
        List of messages to convert

    Returns
    -------
    str
        String representation of the messages

    """

    text_list = [
        # 如果 m 是一个有 .type 属性的对象，并且 type 是 system 或 agent
        f"{m.type.capitalize()}:\n{m.content}" 
        if hasattr(m, 'type') and m.type in ["system", "agent"] 
        # 如果 m 是一个有 .content 属性但没有 .type 的对象 (例如 HumanMessage)
        else m.content if hasattr(m, 'content') 
        # 如果 m 本身就是个字符串
        else str(m)
        for m in messages
    ]

    return "\n".join(text_list)


def chat_and_retry(chat, messages, n_retry, parser):
    """
    Retry querying the chat models until it returns a valid value with a maximum number of retries.

    Parameters:
    -----------
        chat: callable
            A langchain chat object taking a list of messages and returning the llm's message.
        messages: list
            The list of messages so far.
        n_retry: int
            The maximum number of retries.
        parser: callable
            A function taking a message and returning a tuple (value, valid, retry_message)
            where value is the parsed value, valid is a boolean indicating if the value is valid and retry_message
            is a message to display to the user if the value is not valid.

    Returns:
    --------
        value: object
            The parsed value.

    Raises:
    -------
        ValueError: if the value could not be parsed after n_retry retries.

    """
    for i in range(n_retry):
        messages = convert_messages_to_text(messages)
        answer = chat(messages)
        value, valid, retry_message = parser(answer)

        if valid:
            return value

        msg = f"Query failed. Retrying {i+1}/{n_retry}.\n[LLM]:\n{answer}\n[User]:\n{retry_message}"
        warn(msg, RuntimeWarning)
        messages += answer
        messages += retry_message

    return {
        "answer": "Error occured",
        "justification": f"Could not parse a valid value after {n_retry} retries.",
    }


def extract_html_tags(text, keys):
    """Extract the content within HTML tags for a list of keys.

    Parameters
    ----------
    text : str
        The input string containing the HTML tags.
    keys : list of str
        The HTML tags to extract the content from.

    Returns
    -------
    dict
        A dictionary mapping each key to a list of subset in `text` that match the key.

    Notes
    -----
    All text and keys will be converted to lowercase before matching.

    """
    content_dict = {}
    keys = set(keys)
    for key in keys:
        pattern = f"<{key}>(.*?)</{key}>"
        matches = re.findall(pattern, text, re.DOTALL)
        # print(matches)
        if matches:
            content_dict[key] = [match.strip() for match in matches]
    return content_dict


def _parse_human_readable_insight(output):
    """
    A parser that makes sure that the human readable insight is produced in the correct format

    """
    try:
        answer = extract_html_tags(output, ["answer"])
        if "answer" not in answer:
            return (
                "",
                False,
                f"Error: you did not generate answers within the <answer></answer> tags",
            )
        answer = answer["answer"][0]
    except ValueError as e:
        return (
            "",
            False,
            f"The following error occured while extracting the value for the <answer> tag: {str(e)}",
        )

    try:
        justification = extract_html_tags(output, ["justification"])
        if "justification" not in justification:
            return (
                "",
                False,
                f"Error: you did not generate answers within the <justification></justification> tags",
            )
        justification = justification["justification"][0]
    except ValueError as e:
        return (
            "",
            False,
            f"The following error occured while extracting the value for the <justification> tag: {str(e)}",
        )
    try:
        insight = extract_html_tags(output, ["insight"])
        if "insight" not in insight:
            return (
                "",
                False,
                f"Error: you did not generate answers within the <insight></insight> tags",
            )
        insight = insight["insight"][0]
    except ValueError as e:
        return (
            "",
            False,
            f"The following error occured while extracting the value for the <insight> tag: {str(e)}",
        )

    return (
        {"answer": answer, "justification": justification, "insight": insight},
        True,
        "",
    )


def _build_insight_prompt(solution) -> str:
    """
    Gather all plots and statistics produced by the model and format then nicely into text

    """
    insight_prompt = ""
    for i, var in enumerate(solution["vars"]):
        insight_prompt += f"<insight id='{i}'>"
        insight_prompt += f"    <stat>"
        insight_prompt += f"        <name>{var['stat'].get('name', 'n/a')}</name>"
        insight_prompt += f"        <description>{var['stat'].get('description', 'n/a')}</description>"
        stat_val = var["stat"].get("value", "n/a")
        stat_val = stat_val[:50] if isinstance(stat_val, list) else stat_val
        insight_prompt += f"        <value>{stat_val}</value>"
        insight_prompt += f"    </stat>"
        insight_prompt += f"    <plot filename='{var['plot']['name']}'>"
        insight_prompt += f"        <xaxis>"
        insight_prompt += f"            <description>{var['x_axis'].get('description', 'n/a')}</description>"
        x_val = var["x_axis"].get("value", "n/a")
        x_val = x_val[:50] if isinstance(x_val, list) else x_val
        insight_prompt += f"            <value>{x_val}</value>"
        insight_prompt += f"        </xaxis>"
        insight_prompt += f"        <yaxis>"
        insight_prompt += f"            <description>{var['y_axis'].get('description', 'n/a')}</description>"
        y_val = var["y_axis"].get("value", "n/a")
        y_val = y_val[:50] if isinstance(y_val, list) else y_val
        insight_prompt += f"            <value>{y_val}</value>"
        insight_prompt += f"        </yaxis>"
        insight_prompt += f"    </plot>"
        insight_prompt += f"</insight>"
    return insight_prompt


def get_insights(
    context,
    goal,
    messages=[],
    schema=None,
    max_questions=3,
    model_name="gpt-3.5-turbo-0125",
    temperature=0,
):

    chat = get_chat_model(model_name, temperature)

    prompt = prompts.GET_INSIGHTS_TEMPLATE
    messages = [
        SystemMessage(content=prompts.GET_INSIGHTS_SYSTEM_MESSAGE),
        HumanMessage(
            content=prompt.format(
                context=context, goal=goal, schema=schema, max_questions=max_questions
            )
        ),
    ]

    def _validate_tasks(out):
        isights = extract_html_tags(out, ["insight"])

        # Check that there are insights generated
        if "insight" not in isights:
            return (
                out,
                False,
                f"Error: you did not generate insights within the <insight></insight> tags.",
            )
        isights = isights["insight"]
        print("The insights are:", isights)
        print("Length:", len(isights), "   Max:", max_questions)
        return (isights, out), True, ""

    insights, message = chat_and_retry(
        chat, messages, n_retry=3, parser=_validate_tasks
    )

    return insights


def get_questions(
    prompt_method,
    context,
    goal,
    messages=[],
    schema=None,
    max_questions=10,
    model_name="gpt-3.5-turbo-0125",
    temperature=0,
):
    if prompt_method is None:
        prompt_method = "basic"

    prompt, system = prompts.get_question_prompt(method=prompt_method)

    chat = get_chat_model(model_name, temperature)

    messages = [
        SystemMessage(content=system),
        HumanMessage(
            content=prompt.format(
                context=context, goal=goal, schema=schema, max_questions=max_questions
            )
        ),
    ]

    def _validate_tasks(out):
        questions = extract_html_tags(out, ["question"])
        if "question" not in questions:
            return (
                out,
                False,
                f"Error: you did not generate questions within the <question></question> tags",
            )
        questions = questions["question"]
        # Check that there are at most max_questions questions
        if len(questions) > max_questions:
            return (
                out,
                False,
                f"Error: you can only ask at most {max_questions} questions, but you asked {len(questions)}.",
            )

        return (questions, out), True, ""

    questions, message = chat_and_retry(
        chat, messages, n_retry=3, parser=_validate_tasks
    )

    return questions


def get_dataset_description(
    prompt,
    system,
    context,
    goal,
    messages=[],
    schema=None,
    model_name="gpt-3.5-turbo-0125",
    temperature=0,
):

    chat = get_chat_model(model_name, temperature)

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=prompt.format(context=context, goal=goal, schema=schema)),
    ]

    def _validate_tasks(out):
        try:
            questions = extract_html_tags(out, ["description"])["description"]
        except Exception as e:
            return (
                out,
                False,
                f"Error: {str(e)}",
            )

        return (questions, out), True, ""

    data_description, message = chat_and_retry(
        chat, messages, n_retry=2, parser=_validate_tasks
    )

    return data_description


def get_follow_up_questions(
    context,
    goal,
    question,
    answer,
    schema=None,
    max_questions=3,
    model_name="gpt-3.5-turbo-0125",
    prompt_method=None,
    question_type="descriptive",
    temperature=0,
):
    if prompt_method is None:
        prompt_method = "follow_up"

    prompt, system = prompts.get_question_prompt(method=prompt_method)
    chat = get_chat_model(model_name, temperature)

    if prompt_method == "follow_up_with_type":
        content = prompt.format(
            context=context,
            goal=goal,
            question=question,
            answer=answer,
            schema=schema,
            max_questions=max_questions,
            question_type=question_type,
        )

    else:
        content = prompt.format(
            context=context,
            goal=goal,
            question=question,
            answer=answer,
            schema=schema,
            max_questions=max_questions,
        )

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=content),
    ]

    def _validate_tasks(out):
        print(out)
        questions = extract_html_tags(out, ["question"])["question"]
        # print("The questions are:", questions)
        # print("Length:", len(questions), "   Max:", max_questions)

        # Check that there are at most max_questions questions
        if len(questions) > max_questions:
            return (
                out,
                False,
                f"Error: you can only ask at most {max_questions} questions, but you asked {len(questions)}.",
            )

        return (questions, out), True, ""

    questions, message = chat_and_retry(
        chat, messages, n_retry=3, parser=_validate_tasks
    )

    return questions


def select_a_question(
    questions,
    context,
    goal,
    prev_questions,
    model_name="gpt-3.5-turbo-0125",
    prompt_template=None,
    system_template=None,
    temperature=0,
):

    chat = get_chat_model(model_name, temperature)

    followup_questions_formatted = "\n".join(
        [f"{i+1}. {q}\n" for i, q in enumerate(questions)]
    )
    if prev_questions:
        prev_questions_formatted = "\n".join(
            [f"{i+1}. {q}\n" for i, q in enumerate(prev_questions)]
        )
    else:
        prev_questions_formatted = None

    prompt = prompt_template
    messages = [
        SystemMessage(content=system_template),
        HumanMessage(
            content=prompt.format(
                context=context,
                goal=goal,
                prev_questions_formatted=prev_questions_formatted,
                followup_questions_formatted=followup_questions_formatted,
            )
        ),
    ]

    def _validate_tasks(out):
        question_id = extract_html_tags(out, ["question_id"])["question_id"][0]
        # Check that there are at most max_questions questions
        if int(question_id) >= len(questions):
            return (
                out,
                False,
                f"Error: selected question index should be between 0-{len(questions)-1}.",
            )
        return (int(question_id), out), True, ""

    question_id, message = chat_and_retry(
        chat, messages, n_retry=3, parser=_validate_tasks
    )
    return question_id


def generate_code(
    schema,
    multi_schema,
    goal,
    question,
    database_path,
    multi_database_path,
    output_folder,
    n_retries,
    prompt_method=None,
    model_name="gpt-3.5-turbo-0125",
    temperature=0,
):
    """
    Solve a task using the naive single step approach

    See main function docstring for more details

    """
    prompt_template = prompts.get_code_prompt(method=prompt_method)

    available_functions = [
        func_name
        for func_name, obj in inspect.getmembers(tools)
        if inspect.isfunction(obj)
    ]
    function_docs = []
    for func_name in available_functions:
        function_docs.append(
            f"{func_name}{inspect.signature(getattr(tools, func_name))}:\n{inspect.getdoc(getattr(tools, func_name))}\n"
            + "=" * 20
            + "\n"
        )
    function_docs = "\n".join(function_docs)

    
    # create prompt
    full_schema_str = schema_to_str(schema) + "\n"

    # 这是为了适配新的 MULTI_WITH_PATHS_CODE_PROMPT
    if multi_schema and multi_database_path:
        full_schema_str = ""
        database_path = multi_database_path
        # multi_schema 现在是一个 schema 对象的列表
        for i, u_schema in enumerate(multi_schema):
            path = multi_database_path[i] if i < len(multi_database_path) else "N/A"
            full_schema_str += f"--- Dataset {i+1} ---\nFile Path: {path}\nSchema:\n{schema_to_str(u_schema)}\n\n"
    # ### [FIX END] ###

    llm = get_chat_model(model_name, temperature)

    formatted_prompt = prompt_template.format(
        goal=goal,
        question=question,
        schema=full_schema_str,
        database_path=database_path,
        function_docs=function_docs,
    )
    
    if prompt_method == "multi_with_paths": print(formatted_prompt)
    
    output, completions = retry_on_parsing_error(
        llm=llm,
        initial_prompt=formatted_prompt, # <--- 传递格式化好的 prompt
        parser=partial(_code_parser, output_folder=output_folder),
        n_retries=n_retries,
        exception_on_max_retries=False,
    )
    # ### [FIX END] ###


    # Create the output dict
    # Then, iterate over all generated plots and add them to the output dict
    output_dict = {
        "code": completions[-1],
        "prompt": formatted_prompt,
        "code_output": output,
        "message": output,
        "n_retries": len(completions) - 1,
        "goal": goal,
        "question": question,
        "vars": [],
    }

    # write code to a file
    with open(f"{output_folder}/code.py", "w") as file:
        # use regex to capture the python code block
        code = completions[-1]
        try:
            code = re.findall(r"```python(.*?)```", code, re.DOTALL)[0]
            file.write(code.strip())
        except Exception as e:
            print(f"Failed to write code", e)
            file.write(code.strip())

    # Try to load the model's output files
    # TODO: We should detect errors in such files and trigger a retry
    try:
        stat = json.load(open(f"{output_folder}/stat.json", "r"))
    except Exception as e:
        print(f"Failed to load {output_folder}/stat.json", e)
        stat = {}
    try:
        x_axis = json.load(open(f"{output_folder}/x_axis.json", "r"))
    except Exception as e:
        print(f"Failed to load {output_folder}/x_axis.json", e)
        x_axis = {}
    try:
        y_axis = json.load(open(f"{output_folder}/y_axis.json", "r"))
    except Exception as e:
        print(f"Failed to load {output_folder}/y_axis.json", e)
        y_axis = {}

    # Add the plot to the final output dict
    plot_path = f"{output_folder}/plot.jpg"
    stat["type"] = "stat"
    x_axis["type"] = "x_axis"
    y_axis["type"] = "y_axis"
    plot_dict = {"name": plot_path, "type": "plot"}
    output_dict["vars"] += [
        {
            "stat": stat,
            "x_axis": x_axis,
            "y_axis": y_axis,
            "plot": plot_dict,
        }
    ]

    return output_dict


def generate_code(
    schema,
    multi_schema,
    goal,
    question,
    database_path,
    multi_database_path,
    output_folder,
    n_retries,
    prompt_method=None,
    model_name="gpt-3.5-turbo-0125",
    temperature=0,
    multi_profile=None,  # NEW: Add profile information parameter
):
    """
    Generates Python code to answer a question based on provided schemas and data.
    This function is now robust and handles both single-file and multi-file scenarios.
    
    Args:
        schema: Schema for single dataset
        multi_schema: List of schemas for multi-dataset scenarios
        goal: Analysis goal
        question: Question to answer
        database_path: Path to main dataset
        multi_database_path: List of paths for multi-dataset scenarios
        output_folder: Where to save generated code and outputs
        n_retries: Number of retry attempts
        prompt_method: Which prompt template to use
        model_name: LLM model name
        temperature: LLM temperature
        multi_profile: List of statistical profiles for each dataset (NEW)
    """
    prompt_template = prompts.get_code_prompt(method=prompt_method)

    # --- 1. Prepare function documentation ---
    available_functions = [
        func_name
        for func_name, obj in inspect.getmembers(tools)
        if inspect.isfunction(obj)
    ]
    function_docs = "\n".join(
        [
            f"{func_name}{inspect.signature(getattr(tools, func_name))}:\n{inspect.getdoc(getattr(tools, func_name))}\n"
            + "=" * 20
            + "\n"
            for func_name in available_functions
        ]
    )

    # --- 2. Prepare arguments for the prompt template ---
    schema_str = schema_to_str(schema) if schema else None
    format_kwargs = {
        "goal": goal,
        "question": question,
        "database_path": database_path,
        "function_docs": function_docs,
        "schema": schema_str,  # Always include the main schema
    }

    # Conditionally add multi-file arguments if needed by the prompt
    if prompt_method in ["multi", "multi_with_paths"]:
        multi_schema_str = ""
        # multi_schema can be a list of schemas. We need to stringify them all.
        if multi_schema:
            multi_schema_str_list = [schema_to_str(s) for s in multi_schema]
            multi_schema_str = "\n\n---\n\n".join(multi_schema_str_list)

        format_kwargs["multi_schema"] = multi_schema_str
        # Convert list of paths to a string representation for the prompt
        format_kwargs["multi_database_path"] = str(multi_database_path)
        
        # NEW: Add profile information for multi-dataset scenarios
        multi_profile_str = "No profile information available."
        if multi_profile:
            profile_parts = []
            for i, profile in enumerate(multi_profile):
                if isinstance(profile, str):
                    profile_parts.append(f"Dataset {i+1} Profile:\n{profile[:1500]}")  # Limit length
                elif isinstance(profile, dict):
                    profile_parts.append(f"Dataset {i+1} Profile:\n{json.dumps(profile, indent=2)[:1500]}")
            multi_profile_str = "\n\n".join(profile_parts)
        
        format_kwargs["multi_profile"] = multi_profile_str

    # --- 3. Format the prompt and generate code ---
    llm = get_chat_model(model_name, temperature)
    
    # This is now safe and will provide all necessary keys for multi-file prompts
    formatted_prompt = prompt_template.format(**format_kwargs)
    
    output, completions = retry_on_parsing_error(
        llm=llm,
        initial_prompt=formatted_prompt,
        parser=partial(_code_parser, output_folder=output_folder),
        n_retries=n_retries,
        exception_on_max_retries=False,
    )

    # --- 4. Process and return the results ---
    output_dict = {
        "code": completions[-1] if completions else "No code generated.",
        "prompt": formatted_prompt,
        "code_output": output,
        "message": output,
        "n_retries": len(completions) - 1 if completions else n_retries,
        "goal": goal,
        "question": question,
        "vars": [],
    }

    # write code to a file
    if completions:
        with open(os.path.join(output_folder, "code.py"), "w") as file:
            code = extract_python_code_blocks(completions[-1])
            if not code:
                code = completions[-1] # fallback if no blocks found
            file.write(code.strip())

    # Try to load the model's output files
    try:
        stat = json.load(open(os.path.join(output_folder, "stat.json"), "r"))
    except Exception as e:
        print(f"Failed to load {output_folder}/stat.json: {e}")
        stat = {}
    try:
        x_axis = json.load(open(os.path.join(output_folder, "x_axis.json"), "r"))
    except Exception as e:
        print(f"Failed to load {output_folder}/x_axis.json: {e}")
        x_axis = {}
    try:
        y_axis = json.load(open(os.path.join(output_folder, "y_axis.json"), "r"))
    except Exception as e:
        print(f"Failed to load {output_folder}/y_axis.json: {e}")
        y_axis = {}

    # Add the plot to the final output dict
    plot_path = os.path.join(output_folder, "plot.jpg")
    stat["type"] = "stat"
    x_axis["type"] = "x_axis"
    y_axis["type"] = "y_axis"
    plot_dict = {"name": plot_path, "type": "plot"}
    output_dict["vars"].append(
        {
            "stat": stat,
            "x_axis": x_axis,
            "y_axis": y_axis,
            "plot": plot_dict,
        }
    )

    return output_dict


def analysis_nb_to_gt(fname_notebook, include_df_head=False) -> None:
    """
    Reads all ipynb files in data_dir and parses each cell and converts it into a ground truth file.
    The ipynb files are structured as follows: code (outputs plot), then a cell with an insight dict
    """

    def _extract_metadata(nb):
        # iterate through the cells
        metadata = {}
        # extract metadata

        # extract name of the dataset from the first cell
        dname = re.findall(r"## (.+) \(Flag \d+\)", nb.cells[0].source)[0].strip()
        metadata["dataset_name"] = dname
        # extract dataset description
        description = (
            re.findall(
                r"(Dataset Overview|Description)(.+)(Your Objective|Task)",
                nb.cells[0].source,
                re.DOTALL,
            )[0][1]
            .replace("#", "")
            .strip()
        )
        metadata["dataset_description"] = description

        # extract goal and role
        metadata["goal"] = re.findall(r"Goal|Objective\**:(.+)", nb.cells[0].source)[
            0
        ].strip()
        metadata["role"] = re.findall(r"Role\**:(.+)", nb.cells[0].source)[0].strip()

        metadata["difficulty"] = re.findall(
            r"Difficulty|Challenge Level\**: (\d) out of \d", nb.cells[0].source
        )[0].strip()
        metadata["difficulty_description"] = (
            re.findall(
                r"Difficulty|Challenge Level\**: \d out of \d(.+)", nb.cells[0].source
            )[0]
            .replace("*", "")
            .strip()
        )
        metadata["dataset_category"] = re.findall(
            r"Category\**: (.+)", nb.cells[0].source
        )[0].strip()

        # Get Dataset Info
        tag = r"^dataset_path =(.+)"

        dataset_csv_path = None
        for cell in nb.cells:
            if cell.cell_type == "code":
                if re.search(tag, cell.source):
                    dataset_csv_path = (
                        re.findall(tag, cell.source)[0]
                        .strip()
                        .replace("'", "")
                        .replace('"', "")
                    )
                    break
        assert dataset_csv_path is not None
        metadata["dataset_csv_path"] = dataset_csv_path

        if include_df_head:
            metadata["df_head"] = pd.read_html(
                StringIO(cell.outputs[0]["data"]["text/html"])
            )

        # Get Dataset Info
        tag = r"multi_dataset_path =(.+)"

        multi_dataset_csv_path = None
        for cell in nb.cells:
            if cell.cell_type == "code":
                if re.search(tag, cell.source):
                    multi_dataset_csv_path = (
                        re.findall(tag, cell.source)[0]
                        .strip()
                        .replace("'", "")
                        .replace('"', "")
                    )
                    break
        metadata["multi_dataset_csv_path"] = multi_dataset_csv_path

        # Get Summary of Findings
        tag = r"Summary of Findings \(Flag \d+\)(.+)"

        flag = None
        for cell in reversed(nb.cells):
            if cell.cell_type == "markdown":
                if re.search(tag, cell.source, re.DOTALL | re.IGNORECASE):
                    flag = (
                        re.findall(tag, cell.source, re.DOTALL | re.IGNORECASE)[0]
                        .replace("#", "")
                        .replace("*", "")
                        .strip()
                    )
                    break
        assert flag is not None
        metadata["flag"] = flag

        return metadata

    def _parse_question(nb, cell_idx):
        qdict = {}
        qdict["question"] = (
            re.findall(
                r"Question( |-)(\d+).*:(.+)", nb.cells[cell_idx].source, re.IGNORECASE
            )[0][2]
            .replace("*", "")
            .strip()
        )

        if nb.cells[cell_idx + 2].cell_type == "code":
            # action to take to answer the question
            assert nb.cells[cell_idx + 1].cell_type == "markdown"
            qdict["q_action"] = nb.cells[cell_idx + 1].source.replace("#", "").strip()
            assert nb.cells[cell_idx + 2].cell_type == "code"
            qdict["code"] = nb.cells[cell_idx + 2].source
            # extract output plot. Note that this image data is in str,
            # will need to use base64 to load this data

            qdict["plot"] = nb.cells[cell_idx + 2].outputs
            # loop as there might be multiple outputs and some might be stderr
            for o in qdict["plot"]:
                if "data" in o and "image/png" in o["data"]:
                    qdict["plot"] = o["data"]["image/png"]
                    break

            # extract the insight
            try:
                qdict["insight_dict"] = json.loads(nb.cells[cell_idx + 4].source)
            except Exception as e:
                # find the next cell with the insight dict
                for cell in nb.cells[cell_idx + 3 :]:
                    try:
                        qdict["insight_dict"] = json.loads(cell.source)
                        break
                    except Exception as e:
                        continue

        else:
            # print(f"Found prescriptive insight in {fname_notebook}")
            qdict["insight_dict"] = {
                "data_type": "prescriptive",
                "insight": nb.cells[cell_idx + 1].source.strip(),
                "question": qdict["question"],
            }
        return qdict

    def _parse_notebook(nb):
        gt_dict = _extract_metadata(nb)

        # extract questions, code, and outputs
        que_indices = [
            idx
            for idx, cell in enumerate(nb.cells)
            if cell.cell_type == "markdown"
            and re.search(r"Question( |-)\d+", cell.source, re.IGNORECASE)
        ]
        gt_dict["insights"] = []
        for que_idx in que_indices:
            gt_dict["insights"].append(_parse_question(nb, que_idx))
        return gt_dict

    # Convert the notebook to a ground truth file
    if not fname_notebook.endswith(".ipynb"):
        raise ValueError("The file must be an ipynb file")
    else:
        # extract dataset id from flag-analysis-i.ipynb using re
        fname_json = fname_notebook.replace(".ipynb", ".json")

        with open(fname_notebook, "r") as f:
            notebook = nbformat.read(f, as_version=4)
        gt_dict = _parse_notebook(notebook)

    return gt_dict


def get_chat_model(model_name, temperature=0, api_key=None, base_url=None):
    """
    Get a chat model function for the specified model name.
    Supports GPT models and other OpenAI-compatible models (e.g., qwen).

    Args:
        model_name: Name of the model to use
        temperature: Temperature for generation
        api_key: API key (optional, defaults to env var QDF_API_KEY)
        base_url: Base URL for API (optional, defaults to env var QDF_API_URL)

    Returns:
        A lambda function that takes content and returns model response
    """
    # Use provided values, fall back to global config, then environment variables
    key = api_key if api_key else (_global_api_key if _global_api_key else OPENAI_API_KEY)
    url = base_url if base_url else (_global_base_url if _global_base_url else OPENAI_API_URL)
    
    # Debug: Log the key and url (masked)
    import logging
    _logger = logging.getLogger(__name__)
    _logger.warning(f"[get_chat_model] api_key provided: {bool(api_key)}, global: {bool(_global_api_key)}")
    if key:
        _logger.warning(f"[get_chat_model] key starts with: {key[:10] if len(key) > 10 else key}")
    else:
        _logger.warning(f"[get_chat_model] NO API KEY available")
    
    # Create a custom HTTP client without proxy to avoid SOCKS5 issues
    http_client = httpx.Client(proxies={"http://": None, "https://": None})
    client = OpenAI(api_key=key, base_url=url, http_client=http_client)
    llm = (
        lambda content: client.chat.completions.create(
            model=model_name,
            temperature=temperature,
            messages=[{"role": "user", "content": content}],
        )
        .choices[0]
        .message.content
    )
    return llm


class SuppressOutput:
    def __enter__(self):
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")

    def __exit__(self, exc_type, exc_value, traceback):
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr



# --------------------------------------------------

def get_enhanced_data_profile(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate enhanced data profile with statistics for different data types.
    
    Args:
        df: Input DataFrame
        
    Returns:
        JSON string containing comprehensive data profile
    """
    profile = {
        "shape": df.shape,
        "columns_info": {},
        "missing_summary": df.isnull().sum().to_dict()
    }
    
    for col in df.columns:
        col_data = df[col]
        dtype = str(col_data.dtype)
        unique_count = col_data.nunique()
        unique_ratio = unique_count / len(df) if len(df) > 0 else 0
        
        info = {
            "dtype": dtype,
            "unique_count": unique_count,
            "unique_ratio": round(unique_ratio, 4),
            "sample_values": col_data.dropna().unique()[:3].tolist()
        }
        
        # Numeric columns: extract statistical measures
        if np.issubdtype(col_data.dtype, np.number):
            info.update({
                "min": float(col_data.min()) if not pd.isna(col_data.min()) else None,
                "max": float(col_data.max()) if not pd.isna(col_data.max()) else None,
                "avg": round(float(col_data.mean()), 2) if not pd.isna(col_data.mean()) else None,
                "q1": float(col_data.quantile(0.25)),
                "q3": float(col_data.quantile(0.75))
            })
        # Temporal columns: extract date ranges
        elif "datetime" in dtype or col.lower() in ['date', 'time', 'timestamp']:
            try:
                temp_dt = pd.to_datetime(col_data)
                info.update({
                    "min_time": str(temp_dt.min()),
                    "max_time": str(temp_dt.max()),
                    "is_temporal": True
                })
            except: 
                pass  # Skip if conversion fails
            
        profile["columns_info"][col] = info

    # Return as JSON string for LLM consumption
    return json.dumps(profile, ensure_ascii=False, indent=2)


def validate_file_path(file_path: str) -> bool:
    """
    Validate if file exists and is accessible.
    
    Args:
        file_path: Path to check
        
    Returns:
        True if file exists and is readable
    """
    return os.path.exists(file_path) and os.access(file_path, os.R_OK)


def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """
    Safely parse JSON string with error handling.
    
    Args:
        json_str: JSON string to parse
        default: Default value if parsing fails
        
    Returns:
        Parsed JSON object or default value
    """
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default




if __name__ == "__main__":
    # dataset_id = 1
    # results_dir = f"./.tmp/outputs_no_goal/gpt-4-turbo-2024-04-09/{dataset_id}/"
    # data_dir = "/mnt/cba/data/servicenow_incidents/flags"
    # goal = json.load(open(os.path.join(data_dir, f"gt_flag_{dataset_id}.json")))["Goal"]
    # history = json.load(open(os.path.join(results_dir, "history.json")))
    # root_depth_to_prompt(
    #     history=history,
    #     root=1,
    #     depth=3,
    #     goal=goal,
    #     csv_path=os.path.join(data_dir, f"flag-{dataset_id}.csv"),
    #     results_dir=results_dir,
    # )

    analysis_nb_to_gt("/mnt/home/projects/research-cba/.tmp/new_notebooks")
