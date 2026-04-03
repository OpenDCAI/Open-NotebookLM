"""
SQL pattern templates for common analytical queries.

Enhancement 4: Provides abstract SQL patterns for complex analysis operations.
Rather than matching specific few-shot examples, these patterns handle entire
categories of queries (time series, ranking, etc.).

Zero additional LLM cost - all patterns are rule-based and keyword-triggered.
"""
from dataclasses import dataclass
from typing import List, Dict, Optional
import re
import logging

logger = logging.getLogger(__name__)


@dataclass
class SQLPatternTemplate:
    """SQL pattern definition with placeholders."""
    name: str
    trigger_keywords: List[str]  # Case-insensitive keyword matches
    template_sql: str  # SQL with {placeholder} style slots
    required_slots: List[str]  # ["time_col", "value_col", "table"]
    example: str  # Concrete example
    description: str


class SQLPatternService:
    """Provides pattern matching and rendering for common analytical SQL patterns."""

    def __init__(self):
        self.patterns = self._build_patterns()

    def _build_patterns(self) -> List[SQLPatternTemplate]:
        """Define 6 core analytical patterns."""
        return [
            SQLPatternTemplate(
                name="year_over_year",
                trigger_keywords=["同比", "yoy", "year-over-year", "同期对比"],
                template_sql="""
SELECT
  {time_grouping} AS period,
  {current_year} AS current_value,
  {previous_year} AS previous_value,
  ROUND(({current_year} - {previous_year}) * 100.0 / {previous_year}, 2) AS yoy_percent
FROM {table}
WHERE {time_col} >= {date_start}
GROUP BY {time_grouping}
ORDER BY {time_grouping} DESC
LIMIT 100
                """.strip(),
                required_slots=["time_col", "value_col", "table", "time_grouping"],
                example="""
-- 2024 vs 2023 年销售额同比
SELECT
  MONTH(date_column) AS month,
  SUM(CASE WHEN YEAR(date_column) = 2024 THEN amount ELSE 0 END) AS sales_2024,
  SUM(CASE WHEN YEAR(date_column) = 2023 THEN amount ELSE 0 END) AS sales_2023,
  ROUND((SUM(CASE WHEN YEAR(date_column) = 2024 THEN amount ELSE 0 END) -
         SUM(CASE WHEN YEAR(date_column) = 2023 THEN amount ELSE 0 END)) * 100.0 /
        SUM(CASE WHEN YEAR(date_column) = 2023 THEN amount ELSE 0 END), 2) AS yoy_percent
FROM sales
WHERE date_column >= '2023-01-01'
GROUP BY MONTH(date_column)
ORDER BY MONTH(date_column)
                """.strip(),
                description="Year-over-year or month-over-month growth comparison",
            ),
            SQLPatternTemplate(
                name="month_over_month",
                trigger_keywords=["环比", "mom", "month-over-month"],
                template_sql="""
SELECT
  {time_grouping} AS period,
  {value_col} AS current_value,
  LAG({value_col}) OVER (ORDER BY {time_col}) AS previous_value,
  ROUND(({value_col} - LAG({value_col}) OVER (ORDER BY {time_col})) * 100.0 /
        LAG({value_col}) OVER (ORDER BY {time_col}), 2) AS mom_percent
FROM {table}
ORDER BY {time_col}
LIMIT 100
                """.strip(),
                required_slots=["time_col", "value_col", "table", "time_grouping"],
                example="""
SELECT
  DATE(date_column) AS day,
  SUM(amount) AS daily_sales,
  LAG(SUM(amount)) OVER (ORDER BY DATE(date_column)) AS previous_day,
  ROUND((SUM(amount) - LAG(SUM(amount)) OVER (ORDER BY DATE(date_column))) * 100.0 /
        LAG(SUM(amount)) OVER (ORDER BY DATE(date_column)), 2) AS mom_percent
FROM sales
GROUP BY DATE(date_column)
ORDER BY DATE(date_column)
                """.strip(),
                description="Month-over-month or day-over-day growth",
            ),
            SQLPatternTemplate(
                name="top_n_per_group",
                trigger_keywords=["每组前", "top per group", "各个最高", "各自最高"],
                template_sql="""
SELECT * FROM (
  SELECT
    {grouping_col},
    {rank_col},
    ROW_NUMBER() OVER (PARTITION BY {grouping_col} ORDER BY {rank_col} DESC) AS rank
  FROM {table}
) sub
WHERE rank <= {limit_n}
ORDER BY {grouping_col}, rank
                """.strip(),
                required_slots=["table", "grouping_col", "rank_col", "limit_n"],
                example="""
SELECT * FROM (
  SELECT
    city,
    sales_amount,
    ROW_NUMBER() OVER (PARTITION BY city ORDER BY sales_amount DESC) AS rank
  FROM sales
) sub
WHERE rank <= 5
ORDER BY city, rank
                """.strip(),
                description="Top N items within each group (using ROW_NUMBER)",
            ),
            SQLPatternTemplate(
                name="cumulative_sum",
                trigger_keywords=["累计", "running total", "cumulative sum"],
                template_sql="""
SELECT
  {time_col} AS period,
  {value_col} AS value,
  SUM({value_col}) OVER (ORDER BY {time_col} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative
FROM {table}
ORDER BY {time_col}
LIMIT 100
                """.strip(),
                required_slots=["time_col", "value_col", "table"],
                example="""
SELECT
  DATE(date_column) AS date,
  SUM(amount) AS daily_amount,
  SUM(SUM(amount)) OVER (ORDER BY DATE(date_column) ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_amount
FROM sales
GROUP BY DATE(date_column)
ORDER BY DATE(date_column)
                """.strip(),
                description="Cumulative/running total using window functions",
            ),
            SQLPatternTemplate(
                name="percentage_distribution",
                trigger_keywords=["占比", "百分比", "percentage", "proportion"],
                template_sql="""
SELECT
  {category_col},
  SUM({value_col}) AS total,
  ROUND(SUM({value_col}) * 100.0 / (SELECT SUM({value_col}) FROM {table}), 2) AS percentage
FROM {table}
GROUP BY {category_col}
ORDER BY total DESC
LIMIT 100
                """.strip(),
                required_slots=["table", "category_col", "value_col"],
                example="""
SELECT
  product_category,
  SUM(sales_amount) AS total,
  ROUND(SUM(sales_amount) * 100.0 / (SELECT SUM(sales_amount) FROM sales), 2) AS percentage
FROM sales
GROUP BY product_category
ORDER BY total DESC
                """.strip(),
                description="Calculate percentage distribution across categories",
            ),
            SQLPatternTemplate(
                name="date_range_filter",
                trigger_keywords=["最近", "最后", "最近N", "last N", "recent"],
                template_sql="""
SELECT {columns}
FROM {table}
WHERE {time_col} >= CURRENT_DATE - INTERVAL '{N}' {unit}
ORDER BY {time_col} DESC
LIMIT 100
                """.strip(),
                required_slots=["table", "time_col", "N", "unit"],
                example="""
SELECT *
FROM sales
WHERE date_column >= CURRENT_DATE - INTERVAL '30' DAY
ORDER BY date_column DESC
LIMIT 100
                """.strip(),
                description="Filter data by recent time range (last N days/months)",
            ),
        ]

    def match(self, question: str) -> List[SQLPatternTemplate]:
        """
        Match question against pattern triggers.

        Returns:
            List of matching patterns, sorted by relevance (best first).
        """
        question_lower = question.lower()
        matches = []

        for pattern in self.patterns:
            match_score = 0
            for keyword in pattern.trigger_keywords:
                if keyword.lower() in question_lower:
                    match_score += 1

            if match_score > 0:
                matches.append((pattern, match_score))

        # Sort by match score (descending)
        matches.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in matches]

    def get_pattern_hints(self, question: str, max_hints: int = 2) -> List[str]:
        """
        Get pattern hints for prompt injection.

        Returns:
            List of hint strings with pattern name and description.
        """
        matched = self.match(question)
        if not matched:
            return []

        hints = []
        for pattern in matched[:max_hints]:
            hint = f"- {pattern.name}: {pattern.description}"
            hints.append(hint)

        return hints

    def explain_pattern(self, pattern_name: str) -> Dict[str, str]:
        """
        Get detailed explanation of a pattern.

        Returns:
            Dict with 'template', 'example', 'slots' keys.
        """
        for pattern in self.patterns:
            if pattern.name == pattern_name:
                return {
                    "name": pattern.name,
                    "description": pattern.description,
                    "template": pattern.template_sql,
                    "example": pattern.example,
                    "required_slots": pattern.required_slots,
                }
        return {}


# Singleton instance
sql_pattern_service = SQLPatternService()
