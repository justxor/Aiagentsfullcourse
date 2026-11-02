from dataclasses import dataclass

@dataclass
class ToolResult:
    """Класс для хранения результат ответа модели"""
    status: str                 # "ok" | "error"
    content: str = ""
    error_code: str | None = None
    hint: str | None = None
    retryable: bool = False
    truncated: bool = False

    def to_model(self) -> str:
        """То, что реально увидит модель. Ошибка должна быть действенной."""
        if self.status == "ok":
            tail = "\n[...вывод обрезан...]" if self.truncated else ""
            return self.content + tail
        parts = [f"ОШИБКА {self.error_code}"]
        if self.hint:
            parts.append(f"Подсказка: {self.hint}")
        parts.append("Повтор с теми же аргументами не поможет."
                     if not self.retryable else "Повтор возможен.")
        return " ".join(parts)
