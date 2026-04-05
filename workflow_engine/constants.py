# Centralized constants for TableAgent

# ReAct / generation limits
MAX_REACT_STEPS = 7
MAX_GENERATE_ATTEMPTS = 3
MAX_DEBUG_ATTEMPTS = 5

# Tag markers
THINK_TAG_PATTERN = r"<THINK>(.*?)</THINK>"
ACTION_TAG_PATTERN = r"<ACTION>(.*?)</ACTION>"
ANSWER_TAG_PATTERN = r"<ANSWER>(.*?)</ANSWER>"
OBS_TAG_WRAPPER = "<OBSERVATION>{obs}</OBSERVATION>"

# File naming
GENERATED_SCRIPT_NAME = "generated_step.py"
EVAL_RESULT_FILENAME = "eval_result.txt"

# Log truncation
STDOUT_LOG_TRUNCATE = 1000  # characters
CODE_LOG_TRUNCATE = 1200    # characters

# Safety / fallbacks
EMPTY_CODE_FALLBACK = "# Empty code produced by model"

# Benchmark task types
BENCHMARK_TASK_TYPES = [
    # Table Cleaning
    "TableCleaning-ErrorDetectionANDCorrection",
    "TableCleaning-ColumnTypeAnnotation",
    "TableCleaning-DataImputation",
    "TableCleaning-Deduplication",

    # Table Transformation
    "TableTransformation-RowToRowTransform",
    "TableTransformation-SplittingANDConcatenation",
    "TableTransformation-RowColumnSwapping",
    "TableTransformation-Filtering",
    "TableTransformation-Grouping",
    "TableTransformation-Sorting",
    "TableTransformation-ListExtraction",

    # Table Augmentation
    "TableAugmentation-RowPopulation",
    "TableAugmentation-SchemaAugmentation",
    "TableAugmentation-ColumnAugmentation",

    # Table Matching
    "TableMatching-SchemaMatching",
    "TableMatching-EntityMatching"
]

__all__ = [
    'MAX_REACT_STEPS', 'MAX_GENERATE_ATTEMPTS', 'MAX_DEBUG_ATTEMPTS',
    'THINK_TAG_PATTERN', 'ACTION_TAG_PATTERN', 'ANSWER_TAG_PATTERN',
    'OBS_TAG_WRAPPER', 'GENERATED_SCRIPT_NAME', 'EVAL_RESULT_FILENAME',
    'STDOUT_LOG_TRUNCATE', 'CODE_LOG_TRUNCATE', 'EMPTY_CODE_FALLBACK',
    'BENCHMARK_TASK_TYPES'
]