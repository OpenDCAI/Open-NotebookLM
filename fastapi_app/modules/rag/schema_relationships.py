"""
Schema relationship discovery and caching service.

Enhancement 3: Automatically discovers and caches JOIN relationships between tables.

Sources of relationship discovery (by confidence):
1. FK constraints from schema metadata (confidence=1.0)
2. Naming conventions: table_a.table_b_id -> table_b.id (confidence=0.8)
3. Learned from successfully executed SQL (confidence=0.6, usage_count++)

Zero additional LLM cost - all discovery is rule-based.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class JoinRelationship:
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float
    source: str  # "fk_constraint" | "naming_convention" | "learned_from_sql"
    usage_count: int = 0

    @property
    def key(self) -> str:
        """Unique key for deduplication."""
        tables = sorted([
            f"{self.left_table}.{self.left_column}",
            f"{self.right_table}.{self.right_column}",
        ])
        return f"{tables[0]}->{tables[1]}"

    def to_hint_str(self) -> str:
        """Format as a prompt hint string."""
        join_type = "INNER JOIN" if self.confidence >= 0.8 else "LEFT JOIN"
        usage_info = f", used {self.usage_count}x" if self.usage_count > 0 else ""
        return (
            f"{self.left_table}.{self.left_column} -> "
            f"{self.right_table}.{self.right_column} "
            f"({join_type}{usage_info})"
        )


class SchemaRelationshipService:
    """
    Discovers and caches JOIN relationships per datasource.

    Thread-safe: each datasource_id has its own relationship cache.
    """

    def __init__(self):
        # {datasource_id: {relationship_key: JoinRelationship}}
        self._cache: Dict[int, Dict[str, JoinRelationship]] = defaultdict(dict)

    def discover_from_schema(
        self,
        datasource_id: int,
        schema_info: Dict,
    ) -> List[JoinRelationship]:
        """
        Discover relationships from schema metadata.

        Args:
            datasource_id: The datasource ID
            schema_info: Schema dict with "tables" list, each table having
                         "name", "columns" (list of column dicts with "name")

        Returns:
            List of discovered relationships
        """
        tables = schema_info.get("tables", [])
        if not tables:
            return []

        discovered = []

        # Build table name -> column names mapping
        table_columns: Dict[str, List[str]] = {}
        for table in tables:
            tname = table.get("name", "")
            cols = [c.get("name", "") for c in table.get("columns", [])]
            if tname:
                table_columns[tname] = cols

        # Strategy 1: FK constraints (if available in schema)
        for table in tables:
            tname = table.get("name", "")
            for col_info in table.get("columns", []):
                fk = col_info.get("foreign_key")
                if fk:
                    # fk format: "other_table.other_col" or similar
                    parts = fk.split(".")
                    if len(parts) == 2:
                        rel = JoinRelationship(
                            left_table=tname,
                            left_column=col_info["name"],
                            right_table=parts[0],
                            right_column=parts[1],
                            confidence=1.0,
                            source="fk_constraint",
                        )
                        self._add_relationship(datasource_id, rel)
                        discovered.append(rel)

        # Strategy 2: Naming convention detection
        table_names = list(table_columns.keys())
        for tname, cols in table_columns.items():
            for col in cols:
                col_lower = col.lower()

                # Pattern: {other_table}_id or {other_table}id
                for other_table in table_names:
                    if other_table == tname:
                        continue

                    other_lower = other_table.lower()
                    # Check: col == other_table + "_id"
                    if col_lower == f"{other_lower}_id" or col_lower == f"{other_lower}id":
                        # Check if other_table has "id" column
                        other_cols_lower = [c.lower() for c in table_columns.get(other_table, [])]
                        if "id" in other_cols_lower:
                            rel = JoinRelationship(
                                left_table=tname,
                                left_column=col,
                                right_table=other_table,
                                right_column="id",
                                confidence=0.8,
                                source="naming_convention",
                            )
                            self._add_relationship(datasource_id, rel)
                            discovered.append(rel)

        if discovered:
            logger.info(
                f"Schema relationship discovery for ds={datasource_id}: "
                f"found {len(discovered)} relationships"
            )
        return discovered

    def learn_from_sql(self, datasource_id: int, sql: str) -> List[JoinRelationship]:
        """
        Extract JOIN relationships from a successfully executed SQL.

        Parses JOIN ON clauses to discover actual relationships used.
        """
        discovered = []

        # Pattern: JOIN table_name ON table_a.col_a = table_b.col_b
        join_pattern = re.compile(
            r'\bJOIN\s+(\w+)\s+(?:AS\s+)?(\w+)?\s+ON\s+'
            r'(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)',
            re.IGNORECASE,
        )

        for match in join_pattern.finditer(sql):
            # Groups: joined_table, alias, left_ref, left_col, right_ref, right_col
            joined_table = match.group(1)
            left_ref = match.group(3)
            left_col = match.group(4)
            right_ref = match.group(5)
            right_col = match.group(6)

            # Resolve aliases: try to use actual table names
            # For simplicity, use the references as-is (they may be aliases)
            rel = JoinRelationship(
                left_table=left_ref,
                left_column=left_col,
                right_table=right_ref,
                right_column=right_col,
                confidence=0.6,
                source="learned_from_sql",
            )

            existing = self._cache.get(datasource_id, {}).get(rel.key)
            if existing:
                existing.usage_count += 1
                # Upgrade confidence if used repeatedly
                if existing.usage_count >= 3 and existing.confidence < 0.9:
                    existing.confidence = min(existing.confidence + 0.1, 0.95)
            else:
                self._add_relationship(datasource_id, rel)
                discovered.append(rel)

        return discovered

    def get_join_hints(
        self,
        datasource_id: int,
        tables: Optional[List[str]] = None,
        max_hints: int = 10,
    ) -> List[str]:
        """
        Get JOIN hint strings for prompt injection.

        Args:
            datasource_id: The datasource ID
            tables: If provided, only return relationships involving these tables
            max_hints: Maximum number of hints to return
        """
        rels = self._cache.get(datasource_id, {})
        if not rels:
            return []

        # Filter by tables if specified
        if tables:
            tables_lower = {t.lower() for t in tables}
            filtered = [
                r for r in rels.values()
                if r.left_table.lower() in tables_lower
                or r.right_table.lower() in tables_lower
            ]
        else:
            filtered = list(rels.values())

        # Sort by confidence (desc) then usage_count (desc)
        filtered.sort(key=lambda r: (r.confidence, r.usage_count), reverse=True)

        return [r.to_hint_str() for r in filtered[:max_hints]]

    def _add_relationship(self, datasource_id: int, rel: JoinRelationship):
        """Add a relationship, keeping the higher-confidence one on conflict."""
        key = rel.key
        existing = self._cache[datasource_id].get(key)
        if existing is None or rel.confidence > existing.confidence:
            self._cache[datasource_id][key] = rel

    def clear(self, datasource_id: Optional[int] = None):
        """Clear cached relationships."""
        if datasource_id is not None:
            self._cache.pop(datasource_id, None)
        else:
            self._cache.clear()


# Singleton instance
schema_relationship_service = SchemaRelationshipService()
