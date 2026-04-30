"""Token usage tracker for LLM, VLM, and Image Generator."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ModelUsage:
    """Usage statistics for a specific model."""
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0

    def add_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Add token usage from a single API call."""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += prompt_tokens + completion_tokens
        self.call_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model_name": self.model_name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
        }


@dataclass
class StepUsage:
    """Usage statistics for a pipeline step."""
    step_name: str
    llm_usage: dict[str, ModelUsage] = field(default_factory=dict)
    vlm_usage: dict[str, ModelUsage] = field(default_factory=dict)
    image_generation_count: int = 0

    def add_llm_usage(self, model_name: str, prompt_tokens: int, completion_tokens: int) -> None:
        """Add LLM usage."""
        if model_name not in self.llm_usage:
            self.llm_usage[model_name] = ModelUsage(model_name=model_name)
        self.llm_usage[model_name].add_usage(prompt_tokens, completion_tokens)

    def add_vlm_usage(self, model_name: str, prompt_tokens: int, completion_tokens: int) -> None:
        """Add VLM usage."""
        if model_name not in self.vlm_usage:
            self.vlm_usage[model_name] = ModelUsage(model_name=model_name)
        self.vlm_usage[model_name].add_usage(prompt_tokens, completion_tokens)

    def add_image_generation(self, count: int = 1) -> None:
        """Add image generation count."""
        self.image_generation_count += count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "step_name": self.step_name,
            "llm_usage": {name: usage.to_dict() for name, usage in self.llm_usage.items()},
            "vlm_usage": {name: usage.to_dict() for name, usage in self.vlm_usage.items()},
            "image_generation_count": self.image_generation_count,
        }


class TokenTracker:
    """Global token usage tracker."""

    def __init__(self) -> None:
        self.steps: dict[str, StepUsage] = {}
        self.current_step: str | None = None

    def start_step(self, step_name: str) -> None:
        """Start tracking a new step."""
        self.current_step = step_name
        if step_name not in self.steps:
            self.steps[step_name] = StepUsage(step_name=step_name)

    def add_llm_usage(self, model_name: str, prompt_tokens: int, completion_tokens: int, step_name: str | None = None) -> None:
        """Add LLM token usage."""
        step = step_name or self.current_step
        if step is None:
            step = "unknown"
        if step not in self.steps:
            self.steps[step] = StepUsage(step_name=step)
        self.steps[step].add_llm_usage(model_name, prompt_tokens, completion_tokens)

    def add_vlm_usage(self, model_name: str, prompt_tokens: int, completion_tokens: int, step_name: str | None = None) -> None:
        """Add VLM token usage."""
        step = step_name or self.current_step
        if step is None:
            step = "unknown"
        if step not in self.steps:
            self.steps[step] = StepUsage(step_name=step)
        self.steps[step].add_vlm_usage(model_name, prompt_tokens, completion_tokens)

    def add_image_generation(self, count: int = 1, step_name: str | None = None) -> None:
        """Add image generation count."""
        step = step_name or self.current_step
        if step is None:
            step = "unknown"
        if step not in self.steps:
            self.steps[step] = StepUsage(step_name=step)
        self.steps[step].add_image_generation(count)

    def get_total_llm_usage(self) -> dict[str, ModelUsage]:
        """Get total LLM usage across all steps."""
        total: dict[str, ModelUsage] = {}
        for step in self.steps.values():
            for model_name, usage in step.llm_usage.items():
                if model_name not in total:
                    total[model_name] = ModelUsage(model_name=model_name)
                total[model_name].prompt_tokens += usage.prompt_tokens
                total[model_name].completion_tokens += usage.completion_tokens
                total[model_name].total_tokens += usage.total_tokens
                total[model_name].call_count += usage.call_count
        return total

    def get_total_vlm_usage(self) -> dict[str, ModelUsage]:
        """Get total VLM usage across all steps."""
        total: dict[str, ModelUsage] = {}
        for step in self.steps.values():
            for model_name, usage in step.vlm_usage.items():
                if model_name not in total:
                    total[model_name] = ModelUsage(model_name=model_name)
                total[model_name].prompt_tokens += usage.prompt_tokens
                total[model_name].completion_tokens += usage.completion_tokens
                total[model_name].total_tokens += usage.total_tokens
                total[model_name].call_count += usage.call_count
        return total

    def get_total_image_generation_count(self) -> int:
        """Get total image generation count."""
        return sum(step.image_generation_count for step in self.steps.values())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        total_llm = self.get_total_llm_usage()
        total_vlm = self.get_total_vlm_usage()

        return {
            "steps": {name: step.to_dict() for name, step in self.steps.items()},
            "total_llm_usage": {name: usage.to_dict() for name, usage in total_llm.items()},
            "total_vlm_usage": {name: usage.to_dict() for name, usage in total_vlm.items()},
            "total_image_generation_count": self.get_total_image_generation_count(),
            "summary": {
                "total_llm_tokens": sum(usage.total_tokens for usage in total_llm.values()),
                "total_vlm_tokens": sum(usage.total_tokens for usage in total_vlm.values()),
                "total_llm_calls": sum(usage.call_count for usage in total_llm.values()),
                "total_vlm_calls": sum(usage.call_count for usage in total_vlm.values()),
                "total_image_generations": self.get_total_image_generation_count(),
            },
        }

    def save_to_file(self, output_path: str | Path) -> None:
        """Save usage statistics to a JSON file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = self.to_dict()
        output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_to_txt(self, output_path: str | Path) -> None:
        """Save usage statistics to a human-readable text file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines = ["=" * 80, "Token Usage Report", "=" * 80, ""]

        # Summary
        data = self.to_dict()
        summary = data["summary"]
        lines.extend([
            "SUMMARY",
            "-" * 80,
            f"Total LLM Tokens:        {summary['total_llm_tokens']:,}",
            f"Total VLM Tokens:        {summary['total_vlm_tokens']:,}",
            f"Total LLM Calls:         {summary['total_llm_calls']:,}",
            f"Total VLM Calls:         {summary['total_vlm_calls']:,}",
            f"Total Image Generations: {summary['total_image_generations']:,}",
            "",
        ])

        # Total LLM Usage by Model
        if data["total_llm_usage"]:
            lines.extend(["TOTAL LLM USAGE BY MODEL", "-" * 80])
            for model_name, usage in data["total_llm_usage"].items():
                lines.extend([
                    f"Model: {model_name}",
                    f"  Prompt Tokens:     {usage['prompt_tokens']:,}",
                    f"  Completion Tokens: {usage['completion_tokens']:,}",
                    f"  Total Tokens:      {usage['total_tokens']:,}",
                    f"  Call Count:        {usage['call_count']:,}",
                    "",
                ])

        # Total VLM Usage by Model
        if data["total_vlm_usage"]:
            lines.extend(["TOTAL VLM USAGE BY MODEL", "-" * 80])
            for model_name, usage in data["total_vlm_usage"].items():
                lines.extend([
                    f"Model: {model_name}",
                    f"  Prompt Tokens:     {usage['prompt_tokens']:,}",
                    f"  Completion Tokens: {usage['completion_tokens']:,}",
                    f"  Total Tokens:      {usage['total_tokens']:,}",
                    f"  Call Count:        {usage['call_count']:,}",
                    "",
                ])

        # Usage by Step
        lines.extend(["USAGE BY STEP", "-" * 80])
        for step_name, step_data in data["steps"].items():
            lines.append(f"\n{step_name.upper()}")
            lines.append("-" * 40)

            if step_data["llm_usage"]:
                lines.append("  LLM Usage:")
                for model_name, usage in step_data["llm_usage"].items():
                    lines.extend([
                        f"    {model_name}:",
                        f"      Prompt Tokens:     {usage['prompt_tokens']:,}",
                        f"      Completion Tokens: {usage['completion_tokens']:,}",
                        f"      Total Tokens:      {usage['total_tokens']:,}",
                        f"      Call Count:        {usage['call_count']:,}",
                    ])

            if step_data["vlm_usage"]:
                lines.append("  VLM Usage:")
                for model_name, usage in step_data["vlm_usage"].items():
                    lines.extend([
                        f"    {model_name}:",
                        f"      Prompt Tokens:     {usage['prompt_tokens']:,}",
                        f"      Completion Tokens: {usage['completion_tokens']:,}",
                        f"      Total Tokens:      {usage['total_tokens']:,}",
                        f"      Call Count:        {usage['call_count']:,}",
                    ])

            if step_data["image_generation_count"] > 0:
                lines.append(f"  Image Generations: {step_data['image_generation_count']:,}")

            lines.append("")

        lines.append("=" * 80)
        output_path.write_text("\n".join(lines), encoding="utf-8")


# Global tracker instance
_global_tracker: TokenTracker | None = None


def get_global_tracker() -> TokenTracker:
    """Get or create the global token tracker."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = TokenTracker()
    return _global_tracker


def reset_global_tracker() -> None:
    """Reset the global token tracker."""
    global _global_tracker
    _global_tracker = TokenTracker()
