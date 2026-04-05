"""TableAgent utilities - helper functions for table processing workflow."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union
import pandas as pd

from workflow_engine.logger import get_logger

log = get_logger(__name__)


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).resolve().parent.parent


def robust_parse_json(
    text: str,
    *,
    merge_dicts: bool = False,
    strip_double_braces: bool = False
) -> Union[Dict[str, Any], List[Any]]:
    """
    尽量从 LLM / 日志 / jsonl / Markdown 片段中提取合法 JSON。
    """
    s = text.strip()
    s = _remove_markdown_fence(s)
    s = _remove_outer_triple_quotes(s)
    s = _remove_leading_json_word(s)

    if strip_double_braces:
        s = s.replace("{{", "{").replace("}}", "}")

    s = _strip_json_comments(s)
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)

    try:
        result = json.loads(s)
        return result
    except json.JSONDecodeError:
        pass

    objs = _extract_json_objects(s)
    if not objs:
        raise ValueError("Unable to locate any valid JSON fragment.")

    return _maybe_merge(objs, merge_dicts)


def _remove_markdown_fence(src: str) -> str:
    blocks = re.findall(r'```[\w-]*\s*([\s\S]*?)```', src, re.I)
    return "\n".join(blocks).strip() if blocks else src


def _remove_outer_triple_quotes(src: str) -> str:
    if (src.startswith("'''") and src.endswith("'''")) or (
        src.startswith('"""') and src.endswith('"""')
    ):
        return src[3:-3].strip()
    return src


def _remove_leading_json_word(src: str) -> str:
    return src[4:].lstrip() if src.lower().startswith("json") else src


def _strip_json_comments(src: str) -> str:
    src = re.sub(r'/\*[\s\S]*?\*/', '', src)
    src = re.sub(r'(?![:"\'])//.*', '', src)
    src = re.sub(r',\s*([}\]])', r'\1', src)
    return src.strip()


def _extract_json_objects(src: str) -> List[Any]:
    from json import JSONDecoder
    dec = JSONDecoder()
    idx, n = 0, len(src)
    objs: List[Any] = []

    while idx < n:
        m = re.search(r'[{\[]', src[idx:])
        if not m:
            break
        idx += m.start()
        try:
            obj, end = dec.raw_decode(src, idx)
            tail = src[end:].lstrip()
            if tail and tail[0] not in ',]}>\n\r':
                idx += 1
                continue
            objs.append(obj)
            idx = end
        except json.JSONDecodeError:
            idx += 1
    return objs


def _maybe_merge(objs: List[Any], merge_dicts: bool) -> Union[Any, List[Any]]:
    if len(objs) == 1:
        return objs[0]
    if merge_dicts and all(isinstance(o, dict) for o in objs):
        merged: Dict[str, Any] = {}
        for o in objs:
            merged.update(o)
        return merged
    return objs


def get_paths(base_dir: str) -> Tuple[str, str]:
    """获取代码路径和输出目录路径"""
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    code_path = os.path.join(base_dir, 'generated_code.py')
    processed_table_path = os.path.join(base_dir, "results")
    if os.path.exists(processed_table_path):
        shutil.rmtree(processed_table_path)
    os.makedirs(processed_table_path)
    return code_path, processed_table_path


def safe_exec_code(py_path: Union[str, Path], output_path: Union[str, List[str]], input_path: List[Any] = None) -> Tuple[str, float]:
    """安全执行 Python 代码"""
    time_before = time.time()
    py_path = Path(py_path)
    if not os.path.isfile(py_path):
        raise FileNotFoundError(f"Script not found: {py_path}")
    if py_path.suffix.lower() != '.py':
        raise ValueError("Only .py files are allowed")

    if input_path:
        input_args = [str(p) for p in input_path]
        result = subprocess.run(
            [sys.executable, str(py_path), "--input", *input_args, "--output", str(output_path)],
            capture_output=True,
            text=True,
            timeout=600
        )
    else:
        output_args = [arg for out in output_path for arg in ("--output", out)]
        result = subprocess.run(
            [sys.executable, str(py_path), *output_args],
            capture_output=True,
            text=True,
            timeout=600
        )

    if result.returncode != 0:
        raise RuntimeError(f"Script failed:\n{result.stderr}")

    return result.stdout.strip(), time.time() - time_before


def extract_python_code_block(content: str) -> str:
    """从内容中提取 Python 代码块"""
    match = re.search(r"```python\s*(.*?)\s*```", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content.strip() or "# Empty code"


def write_code_file(res_path: str, code: str) -> Path:
    """写入代码文件"""
    code_path, _ = get_paths(res_path)
    Path(code_path).write_text(code, encoding="utf-8")
    return Path(code_path)


def parse_react_output(raw: str) -> Dict[str, Any]:
    """解析 ReAct 风格的输出"""
    from workflow_engine.constants import (
        THINK_TAG_PATTERN, ACTION_TAG_PATTERN, ANSWER_TAG_PATTERN
    )

    result = {"thinks": [], "action_code": None, "answer_obj": None, "errors": []}
    think_blocks = re.findall(THINK_TAG_PATTERN, raw, re.DOTALL | re.IGNORECASE)
    result["thinks"] = [t.strip() for t in think_blocks if t.strip()]

    answer_match = re.search(ANSWER_TAG_PATTERN, raw, re.DOTALL)
    if answer_match:
        ans_raw = answer_match.group(1)
        try:
            result["answer_obj"] = json.loads(ans_raw)
        except Exception:
            result["answer_obj"] = ans_raw.strip()

    action_match = re.search(ACTION_TAG_PATTERN, raw, re.DOTALL | re.IGNORECASE)
    if action_match and result["answer_obj"] is None:
        act_raw = action_match.group(1)
        try:
            result["action_code"] = extract_python_code_block(act_raw)
        except Exception as e:
            result["errors"].append(f"action_json_parse_failed: {e}")

    return result


def observation_to_message(obs: Dict[str, Any]) -> str:
    """将观察结果转换为消息"""
    from workflow_engine.constants import OBS_TAG_WRAPPER
    return OBS_TAG_WRAPPER.format(obs=json.dumps(obs, ensure_ascii=False, separators=(",", ":")))


def truncate_for_log(text: str, limit: int = 1000) -> str:
    """截断日志文本"""
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def load_config(config_path: str) -> Dict[str, Any]:
    """加载 YAML 配置文件"""
    import yaml
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def profile_multiple_csvs(csv_paths: List[str], output_dir: str) -> Dict[str, Any]:
    """对多个 CSV 文件进行数据画像"""
    import pandas as pd

    all_profiles = {}
    for file_path in csv_paths:
        path = Path(file_path)
        try:
            df = _read_file_as_dataframe(path)
            profile = _simple_data_profile(df)
            profile["filename"] = path.name
            all_profiles[path.name] = profile
        except Exception as e:
            all_profiles[path.name] = {"error": str(e), "file_path": str(path)}

    output_path = Path(output_dir) / "default_data_profiling.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_profiles, f, indent=2, ensure_ascii=False)

    return all_profiles


def _simple_data_profile(df: pd.DataFrame) -> dict:
    """为单个 DataFrame 生成轻量级数据概要"""
    profile = {
        "num_rows": len(df),
        "num_columns": df.shape[1],
        "columns": {}
    }

    for col in df.columns:
        series = df[col]
        col_info = {
            "dtype": str(series.dtype),
            "non_null_count": int(series.count()),
            "null_count": int(series.isnull().sum()),
            "unique_count": int(series.nunique(dropna=True)),
        }

        if pd.api.types.is_numeric_dtype(series):
            col_info["stats"] = {
                "mean": float(series.mean()) if not series.isna().all() else None,
                "std": float(series.std()) if not series.isna().all() else None,
                "min": float(series.min()) if not series.isna().all() else None,
                "max": float(series.max()) if not series.isna().all() else None,
            }
        elif pd.api.types.is_string_dtype(series) or series.dtype == 'object':
            top_values = series.value_counts().head(10).to_dict()
            col_info["top_values"] = {str(k): int(v) for k, v in top_values.items()}

        profile["columns"][col] = col_info

    return profile


def _read_file_as_dataframe(path: Path) -> pd.DataFrame:
    """智能读取 CSV / JSON / JSONL"""
    import pandas as pd

    suffix = path.suffix.lower()

    try:
        if suffix == '.json':
            df = pd.read_json(path)
            if isinstance(df, pd.Series) or (len(df) == 1 and isinstance(df.iloc[0], (dict, list))):
                with open(path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                if isinstance(raw, dict) and 'data' in raw:
                    df = pd.json_normalize(raw['data'])
                elif isinstance(raw, list):
                    df = pd.json_normalize(raw)
                else:
                    df = pd.json_normalize([raw]) if isinstance(raw, dict) else pd.DataFrame()
        elif suffix == '.jsonl':
            records = []
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            df = pd.json_normalize(records)
        elif suffix == '.csv':
            df = pd.read_csv(path)
        else:
            raise ValueError(f"Unsupported file extension: {suffix}")

        return df

    except Exception as e:
        raise RuntimeError(f"Failed to read {path.name}: {e}")


def write_eval_result(state: Dict[str, Any]) -> None:
    """写入评估结果"""
    from workflow_engine.constants import EVAL_RESULT_FILENAME

    llm_tracker = state.get("llm_tracker")
    if llm_tracker:
        summary = llm_tracker.summary()
        money_cost = summary.get("total_cost_usd", 0.0)
        input_tokens = summary.get("input_tokens", 0)
        output_tokens = summary.get("output_tokens", 0)
        completion_time = summary.get("completion_time_sec", 0.0)
    else:
        money_cost = input_tokens = output_tokens = completion_time = 0.0

    task_name = state.get("task_name", "unknown")
    profiling = state.get("data_profiling", {})

    eval_result_path = os.path.join(state.get("result_path", state.get("res_path", "")), EVAL_RESULT_FILENAME)
    summary_lines = [
        f"task_name: {task_name}",
        f"input_tokens: {input_tokens}",
        f"output_tokens: {output_tokens}",
        f"completion_time: {completion_time:.3f}",
        f"execution_time: {state.get('execution_time', 0):.3f}",
        f"Money Cost: {money_cost:.3f}",
        "",
        f"generated_attempts: {state.get('attempts', 0)}",
        f"debug_total_attempts: {state.get('debug_total_attempts', 0)}",
        f"script_generated_total: {state.get('script_generated_total', 0)}",
        f"script_runnable_total: {state.get('script_runnable_total', 0)}",
        "",
    ]

    data_profiling_path = os.path.join(state.get("result_path", state.get("res_path", "")), "data_profiling.json")
    try:
        with open(data_profiling_path, "w", encoding="utf-8") as f:
            json.dump(profiling, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    error_logs = state.get("error_logs", [])
    if error_logs:
        summary_lines.append("Error Logs:")
        summary_lines.extend(error_logs)

    content = "\n".join(summary_lines) + "\n"
    with open(eval_result_path, "w", encoding="utf-8") as f:
        f.write(content)
