from dataclasses import dataclass, field
from .Task import Task
import time

@dataclass
class Budget:
    task: Task
    started: float = field(default_factory=time.monotonic)
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0
    empty_steps: int = 0
    warned: bool = False

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def exceeded(self) -> str | None:
        if self.steps >= self.task.max_steps:
            return "budget_steps"
        if self.elapsed() >= self.task.max_seconds.seconds:
            return "budget_time"
        if self.tokens >= self.task.max_tokens:
            return "budget_tokens"
        if self.cost_usd >= self.task.max_cost_usd:
            return "budget_cost"
        return None

    def ratios(self) -> dict[str, float]:
        return {
            "steps": self.steps / max(self.task.max_steps, 1),
            "time": self.elapsed() / max(self.task.max_seconds.seconds, 1e-9),
            "tokens": self.tokens / max(self.task.max_tokens, 1),
            "cost": self.cost_usd / max(self.task.max_cost_usd, 1e-9),
        }

    def soft_warning(self) -> str | None:
        """Мягкий порог 80%: агент успевает подвести итог, а не обрубается."""
        if self.warned:
            return None
        worst = max(self.ratios().values())
        if worst >= 0.8:
            self.warned = True
            return (
                "ВНИМАНИЕ: бюджет прогона израсходован более чем на 80%. "
                "Заверши работу: дай лучший доступный ответ и явно перечисли, "
                "что осталось непроверенным."
            )
        return None

    def snapshot(self) -> dict[str, str]:
        return {
            "steps": f"{self.steps}/{self.task.max_steps}",
            "tokens": f"{self.tokens}/{self.task.max_tokens}",
            "cost": f"{self.cost_usd:.4f}/{self.task.max_cost_usd}",
            "seconds": f"{self.elapsed():.1f}/{self.task.max_seconds}",
        }

