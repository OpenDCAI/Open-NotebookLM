import matplotlib
import matplotlib.pyplot as plt
import json, pandas as pd, os
import numpy as np 
from typing import Dict, List, Optional, Union, Callable
from copy import deepcopy
from wordcloud import WordCloud
import seaborn as sns
from functools import wraps
import warnings

def setup():
    """
    Set up Chinese font for matplotlib to ensure proper display of Chinese characters.
    Tries multiple font options in order of preference, prioritizing the provided font file.
    """
    # Priority 1: Use the provided font file if it exists (highest priority)
    primary_font_path = "/mnt/DataFlow/qry/DM/DataManus/src/insight/utils/simhei.ttf"
    
    if os.path.exists(primary_font_path):
        try:
            matplotlib.font_manager.fontManager.addfont(primary_font_path)
            font_prop = matplotlib.font_manager.FontProperties(fname=primary_font_path)
            font_name = font_prop.get_name()
            plt.rcParams['font.sans-serif'] = [font_name] + plt.rcParams['font.sans-serif']
            plt.rcParams['axes.unicode_minus'] = False
            # Test if the font works by creating a test figure
            test_fig = plt.figure(figsize=(1, 1))
            plt.close(test_fig)
            return True
        except Exception as e:
            print(f"Warning: Failed to load primary font from {primary_font_path}: {e}")
    
    # Priority 2: Try other custom font paths
    custom_font_paths = [
        "/home/ubuntu/qiruyi/DM/DataManus/src/insight/utils/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    
    for font_path in custom_font_paths:
        if os.path.exists(font_path):
            try:
                matplotlib.font_manager.fontManager.addfont(font_path)
                font_prop = matplotlib.font_manager.FontProperties(fname=font_path)
                font_name = font_prop.get_name()
                plt.rcParams['font.sans-serif'] = [font_name] + plt.rcParams['font.sans-serif']
                plt.rcParams['axes.unicode_minus'] = False
                test_fig = plt.figure(figsize=(1, 1))
                plt.close(test_fig)
                return True
            except Exception as e:
                continue
    
    # Priority 3: Try system fonts
    font_options = [
        'Noto Sans CJK SC',
        'Noto Sans CJK TC',
        'SimHei',
        'Microsoft YaHei',
        'Droid Sans Fallback',
        'WenQuanYi Micro Hei',
        'WenQuanYi Zen Hei',
    ]
    
    for font_name in font_options:
        try:
            plt.rcParams['font.sans-serif'] = [font_name] + plt.rcParams['font.sans-serif']
            plt.rcParams['axes.unicode_minus'] = False
            # Test if the font works
            test_fig = plt.figure(figsize=(1, 1))
            plt.close(test_fig)
            return True
        except:
            continue
    
    # If all else fails, use DejaVu Sans (won't show Chinese but won't crash)
    print("Warning: No Chinese font found. Chinese characters may not display correctly.")
    plt.rcParams['axes.unicode_minus'] = False
    return False


# 【新增】一个自定义的 JSON 编码器，用于处理
class CustomJSONEncoder(json.JSONEncoder):
    """
    自定义 JSON 编码器，用于处理标准库无法序列化的类型
    (例如 numpy.int64, pandas.Timestamp)
    """
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat() # 将 Timestamp 转换为 ISO 格式的字符串
        if isinstance(obj, pd.Series):
            return obj.tolist()
        # 处理其他无法序列化的类型（例如，如果LLM返回了集合）
        if isinstance(obj, set):
            return list(obj)
        
        # 让基类来处理它不知道的类型
        return super(CustomJSONEncoder, self).default(obj)


def plot_countplot(df: pd.DataFrame, plot_column: str, plot_title: str) -> None:
    """
    Takes a DataFrame as input, performs a group by on plot_column and saves a count plot.
    The plot is then saved into plot.jpg

    Parameters:
    df: DataFrame containing the data.
    plot_column: Column name to plot.
    plot_title: Title of the plot.

    Example usage:
    >>> data = pd.DataFrame({
    ...     'category': ['A', 'B', 'A', 'B', 'A'],
    ... })
    >>> plot_column = 'category'
    >>> plot_title = 'Category count plot'
    >>> plot_countplot(data, plot_column)
    """
    # make countplot with plot title using seaborn
    sns.countplot(data=df, x=plot_column, hue=plot_column).set_title(plot_title)
    plt.savefig("plot.jpg")
    plt.close()


def plot_lines(
    df: pd.DataFrame, x_column: str, plot_columns: List[str], plot_title: str
) -> None:
    """
    Takes a DataFrame as input, and makes a line plot of the data in plot_columns using seaborn.
    The plot is then saved into plot.jpg

    Parameters:
    df: DataFrame containing the data.
    x_column: Column name with the x-axis data.
    plot_columns: Columns with y-axis data to plot.
    plot_title: Title of the plot.

    Example usage:
    >>> data = pd.DataFrame({
    ...     'time': [10, 20, 30, 40, 50],
    ...     'A': [1, 2, 3, 4, 5],
    ...     'B': [5, 4, 3, 2, 1],
    ... })
    >>> x_column = 'time'
    >>> plot_columns = ['A', 'B']
    >>> plot_title = 'Line plot of A and B'
    >>> plot_lines(data, x_column, plot_columns)
    """
    # make lineplot with plot title using seaborn
    for plot_column in plot_columns:
        df[x_column] = df[x_column].astype(str)
        sns.lineplot(data=df, x=x_column, y=plot_column, label=plot_column)
    # set plot title
    plt.title(plot_title)
    plt.savefig("plot.jpg")
    plt.close()


def save_json(data_dict: Dict, ftype: str) -> None:
    """
    Saves data_dict to a json file.

    Parameters:
    data_dict: Dictionary containing data to be saved.
    ftype: One of "stat", "x_axis", or "y_axis".

    Example usage:
    >>> ftype = "x_axis"
    >>> data_dict = {
    ...     'name': "X-axis",
    ...     'description': "Different x-axis values for the plot.",
    ...     'value': ["apple", "orange", "banana", "grapes"],
    ... }
    >>> save_json(data_dict, ftype)
    """

    def validate_dict(parent):
        """
        Goes through all the keys in the dictionary and converts the keys are strings.
        If the values are dictionaries, it recursively fixes them as well.
        """
        duplicate = deepcopy(parent)
        for k, v in duplicate.items():
            if isinstance(v, dict):
                parent[k] = validate_dict(v)
            if not isinstance(k, str):
                parent[str(k)] = parent.pop(k)
        return parent

    ftype = ftype.lower()
    if "stat" in ftype:
        ftype = "stat"
    elif "x_axis" in ftype:
        ftype = "x_axis"
    elif "y_axis" in ftype:
        ftype = "y_axis"

    assert all(isinstance(k, str) for k in data_dict.keys())
    # perform a sanity check that all the keys are strings
    validate_dict(data_dict)
    # recursively check if all the keys are strings

    # filename depends on the number of plots already in the folder
    ftype_count = len([f for f in os.listdir() if f.startswith(f"{ftype}_")])
    fname = f"{ftype}.json"
    with open(fname, "w", encoding='utf-8') as f:
        # 【修改】 使用我们自定义的编码器，并确保中文正常显示
        json.dump(data_dict, f, indent=4, cls=CustomJSONEncoder, ensure_ascii=False)


def generate_wordcloud(
    df: pd.DataFrame, group_by_column: str, plot_column: str
) -> None:
    """
    Generates a wordcloud by performing a groupby on df and using the plot_column.
    The plot is then saved into plot.jpg

    Parameters:
    df: DataFrame containing the data.
    group_by_column: Column name to group by.
    plot_column: Column name to plot.

    Example usage:
    >>> data = pd.DataFrame({
    ...     'category': ['A', 'B', 'A', 'B', 'A'],
    ...     'description': ['apple', 'orange', 'banana', 'grapes', 'kiwi'],
    ... })
    >>> group_by_column = 'category'
    >>> plot_column = 'description'
    >>> generate_wordcloud(data, group_by_column, plot_column)
    """
    # check if data in plot_column is a string
    assert isinstance(df[plot_column].iloc[0], str)

    # group by the column and aggregate the data
    grouped_data = df.groupby(group_by_column)[plot_column].apply(list).reset_index()
    # generate a wordcloud for each group
    plt.figure(figsize=(20, 10))
    for i, row in grouped_data.iterrows():
        wc = WordCloud(width=800, height=400).generate(" ".join(row[plot_column]))
        plt.subplot(1, len(grouped_data), i + 1)
        plt.imshow(wc, interpolation="bilinear")
        plt.title(row[group_by_column])
        plt.axis("off")
    plt.savefig("plot.jpg")
    plt.close()


def linear_regression(X, y):
    """
    Fits a linear regression model on the data and returns the model.

    Parameters:
    X: Features to fit the model on.
    y: Target variable to predict.

    Example usage:
    >>> X = np.array([1, 2, 3, 4, 5]).reshape(-1, 1)
    >>> y = np.array([2, 4, 6, 8, 10])
    >>> model = linear_regression(X, y)
    """
    from sklearn.linear_model import LinearRegression

    model = LinearRegression()
    model.fit(X, y)
    return model


def fix_fnames():
    """
    Renames all the plot and stat files in the current directory to plot_<number>.jpg.
    """
    for i, f in enumerate([f for f in os.listdir() if f.startswith("plot")]):
        if f.startswith("plot"):
            os.rename(f, f"plot.jpg")

    for i, f in enumerate([f for f in os.listdir() if f.startswith("stat")]):
        if f.startswith("stat"):
            os.rename(f, f"stat.json")

    for i, f in enumerate([f for f in os.listdir() if f.startswith("x_axis")]):
        if f.startswith("x_axis"):
            os.rename(f, f"x_axis.json")

    for i, f in enumerate([f for f in os.listdir() if f.startswith("y_axis")]):
        if f.startswith("y_axis"):
            os.rename(f, f"y_axis.json")


# =============================================================================
# Robust Utility Functions - Added for improved code execution reliability
# =============================================================================

def safe_datetime_parse(
    series: pd.Series, 
    formats: Optional[List[str]] = None,
    errors: str = 'coerce'
) -> pd.Series:
    """
    Safely parse a pandas Series to datetime, trying multiple formats automatically.
    
    This function attempts to convert a Series to datetime using various common formats.
    It handles mixed formats and returns NaT for unparseable values when errors='coerce'.
    
    Parameters:
    -----------
    series : pd.Series
        The Series containing date/time values to parse.
    formats : List[str], optional
        List of datetime format strings to try. If None, uses common formats.
    errors : str, default 'coerce'
        How to handle parsing errors: 'coerce' (return NaT), 'raise', or 'ignore'.
    
    Returns:
    --------
    pd.Series
        A Series with datetime64[ns] dtype.
    
    Example usage:
    >>> dates = pd.Series(['2023-01-15', '15/01/2023', '01-15-2023', 'invalid'])
    >>> parsed = safe_datetime_parse(dates)
    >>> print(parsed.dtype)  # datetime64[ns]
    """
    if series.empty:
        return pd.Series(dtype='datetime64[ns]')
    
    # Default formats to try
    default_formats = [
        '%Y-%m-%d',           # 2023-01-15
        '%Y/%m/%d',           # 2023/01/15
        '%d-%m-%Y',           # 15-01-2023
        '%d/%m/%Y',           # 15/01/2023
        '%m-%d-%Y',           # 01-15-2023
        '%m/%d/%Y',           # 01/15/2023
        '%Y-%m-%d %H:%M:%S',  # 2023-01-15 14:30:00
        '%Y/%m/%d %H:%M:%S',  # 2023/01/15 14:30:00
        '%d-%m-%Y %H:%M:%S',  # 15-01-2023 14:30:00
        '%Y%m%d',             # 20230115
        '%Y-%m-%dT%H:%M:%S',  # ISO format
        '%Y-%m-%dT%H:%M:%SZ', # ISO format with Z
    ]
    
    formats_to_try = formats if formats else default_formats
    
    # First, try pandas' intelligent parser
    try:
        result = pd.to_datetime(series, errors=errors, infer_datetime_format=True)
        if result.notna().any():
            return result
    except Exception:
        pass
    
    # Try each format explicitly
    for fmt in formats_to_try:
        try:
            result = pd.to_datetime(series, format=fmt, errors='coerce')
            # If more than 50% parsed successfully, use this format
            if result.notna().sum() > len(series) * 0.5:
                return result
        except Exception:
            continue
    
    # Fallback: try generic parsing with coerce
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(series, errors=errors)


def safe_numeric_convert(
    series: pd.Series,
    downcast: Optional[str] = None,
    fill_value: Optional[Union[int, float]] = None
) -> pd.Series:
    """
    Safely convert a pandas Series to numeric type, handling mixed types gracefully.
    
    This function handles common issues like:
    - Strings mixed with numbers (e.g., '1,234' or '50%')
    - Currency symbols (e.g., '$100', '€50')
    - Whitespace and special characters
    - Empty strings and None values
    
    Parameters:
    -----------
    series : pd.Series
        The Series to convert to numeric.
    downcast : str, optional
        Downcast to 'integer', 'signed', 'unsigned', or 'float' for memory efficiency.
    fill_value : int or float, optional
        Value to use for non-convertible entries. If None, uses NaN.
    
    Returns:
    --------
    pd.Series
        A Series with numeric dtype.
    
    Example usage:
    >>> mixed = pd.Series(['100', '1,234', '$50.5', '75%', 'N/A', None])
    >>> numeric = safe_numeric_convert(mixed)
    >>> print(numeric.tolist())  # [100.0, 1234.0, 50.5, 75.0, nan, nan]
    """
    if series.empty:
        return pd.Series(dtype='float64')
    
    # Work on a copy
    result = series.copy()
    
    # Convert to string for consistent processing
    result = result.astype(str)
    
    # Remove common non-numeric characters
    # Currency symbols
    result = result.str.replace(r'[$€£¥₹]', '', regex=True)
    # Thousands separators (comma)
    result = result.str.replace(',', '', regex=False)
    # Percentage signs (but keep the number)
    result = result.str.replace('%', '', regex=False)
    # Whitespace
    result = result.str.strip()
    # Common null representations
    result = result.replace(['', 'nan', 'NaN', 'null', 'NULL', 'None', 'N/A', 'n/a', '-', '--'], np.nan)
    
    # Convert to numeric
    result = pd.to_numeric(result, errors='coerce', downcast=downcast)
    
    # Fill NaN values if specified
    if fill_value is not None:
        result = result.fillna(fill_value)
    
    return result


def handle_empty_dataframe(operation_name: str = "operation"):
    """
    Decorator to handle empty DataFrame scenarios gracefully.
    
    This decorator wraps functions that operate on DataFrames and provides
    informative error messages when the DataFrame is empty or has no valid data.
    
    Parameters:
    -----------
    operation_name : str
        Name of the operation for error messages.
    
    Returns:
    --------
    Callable
        Decorated function with empty DataFrame handling.
    
    Example usage:
    >>> @handle_empty_dataframe("aggregation")
    ... def compute_stats(df: pd.DataFrame, column: str) -> Dict:
    ...     return {
    ...         'mean': df[column].mean(),
    ...         'sum': df[column].sum()
    ...     }
    >>> 
    >>> result = compute_stats(pd.DataFrame(), 'value')  # Returns empty dict with warning
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Find DataFrame in arguments
            df = None
            for arg in args:
                if isinstance(arg, pd.DataFrame):
                    df = arg
                    break
            if df is None:
                for key, value in kwargs.items():
                    if isinstance(value, pd.DataFrame):
                        df = value
                        break
            
            # Check if DataFrame is empty
            if df is not None and df.empty:
                warnings.warn(
                    f"Empty DataFrame provided to {operation_name}. "
                    f"Returning default empty result.",
                    UserWarning
                )
                # Try to return a sensible default based on return type hints
                return_type = func.__annotations__.get('return', None)
                if return_type == dict or return_type == Dict:
                    return {}
                elif return_type == list or return_type == List:
                    return []
                elif return_type == pd.DataFrame:
                    return pd.DataFrame()
                elif return_type == pd.Series:
                    return pd.Series(dtype='float64')
                else:
                    return None
            
            # Check if DataFrame has all NaN values in relevant columns
            if df is not None and len(df) > 0:
                # Check if all values are NaN
                if df.isna().all().all():
                    warnings.warn(
                        f"DataFrame contains only NaN values for {operation_name}. "
                        f"Results may be unreliable.",
                        UserWarning
                    )
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


def validate_columns(df: pd.DataFrame, required_columns: List[str], operation_name: str = "operation") -> bool:
    """
    Validate that required columns exist in a DataFrame.
    
    Parameters:
    -----------
    df : pd.DataFrame
        The DataFrame to validate.
    required_columns : List[str]
        List of column names that must be present.
    operation_name : str
        Name of the operation for error messages.
    
    Returns:
    --------
    bool
        True if all columns exist.
    
    Raises:
    -------
    KeyError
        If any required column is missing, with helpful suggestions.
    
    Example usage:
    >>> df = pd.DataFrame({'A': [1, 2], 'B': [3, 4]})
    >>> validate_columns(df, ['A', 'C'], 'analysis')  # Raises KeyError with suggestions
    """
    missing = [col for col in required_columns if col not in df.columns]
    
    if missing:
        available = df.columns.tolist()
        # Find similar column names for suggestions
        suggestions = {}
        for m in missing:
            similar = [c for c in available if m.lower() in c.lower() or c.lower() in m.lower()]
            if similar:
                suggestions[m] = similar
        
        error_msg = f"Missing columns for {operation_name}: {missing}\n"
        error_msg += f"Available columns: {available}\n"
        if suggestions:
            error_msg += "Possible matches:\n"
            for m, s in suggestions.items():
                error_msg += f"  '{m}' -> {s}\n"
        
        raise KeyError(error_msg)
    
    return True
            