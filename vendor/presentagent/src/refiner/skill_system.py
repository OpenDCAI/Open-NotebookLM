"""Skill system for IR refinement agent."""

from typing import Any, Dict, Protocol


class Skill(Protocol):
    """Skill protocol - all skills must implement this interface."""

    name: str
    description: str

    def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute the skill with given parameters.

        Returns:
            Result dictionary with at least {"success": bool}
        """
        ...


class SkillRegistry:
    """Global skill registry for IR refinement agent."""

    _skills: Dict[str, Any] = {}

    @classmethod
    def register(cls, skill: Any) -> None:
        """Register a skill."""
        cls._skills[skill.name] = skill

    @classmethod
    def get(cls, name: str) -> Any:
        """Get a skill by name."""
        return cls._skills.get(name)

    @classmethod
    def list_skills(cls) -> list[Dict[str, str]]:
        """List all registered skills."""
        return [
            {"name": skill.name, "description": skill.description}
            for skill in cls._skills.values()
        ]

    @classmethod
    def clear(cls) -> None:
        """Clear all registered skills (for testing)."""
        cls._skills.clear()
