from dataclasses import dataclass, field
from typing import Callable
from .ValueObject import Prompt, Seconds, ModelAnswer

@dataclass(frozen=True)
class Task:
    """Иммутабельна: агент не имеет права переписать задачу под себя."""
    prompt: Prompt
    postcondition: Callable[[ModelAnswer], tuple[bool, str]] | None = None
    max_steps: int = 16
    max_seconds: Seconds = field(default_factory=lambda: Seconds(300))
    max_tokens: int = 200_000
    max_cost_usd: float = 0.5