from typing import Any, Iterable, Callable
from dataclasses import dataclass
import hashlib
import json
from .ToolsResult import ToolResult


MAX_TOOL_OUTPUT = 4000  # символов; всё лишнее обрезается с флагом truncated


@dataclass
class Tool:
    """Класс, описывающий конкретный инструмент"""
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., str]


class ToolRegistry:
    """Класс ответственный за хранение всех инструментов, их использование и схемы(параметры функции и их описание)"""
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    @staticmethod
    def fingerprint(call: dict[str, Any]) -> str:
        """Хеш (имя + нормализованные аргументы) для детектора повторов."""
        payload = json.dumps(
            {"n": call["name"], "a": call.get("arguments", {})},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def invoke(self, call: dict[str, Any]) -> ToolResult:
        """Никогда не выбрасывает наружу: всё превращается в ToolResult."""
        name = call.get("name", "")
        args = call.get("arguments", {}) or {}
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                status="error", error_code="unknown_tool", retryable=False,
                hint="Доступные инструменты: " + ", ".join(sorted(self._tools)),
            )
        missing = [k for k in tool.parameters.get("required", []) if k not in args]   #Сильная зависимость на наличии в parameters словаря с ключом "required"
        if missing:
            return ToolResult(
                status="error", error_code="missing_argument", retryable=True,
                hint=f"Не переданы обязательные аргументы: {', '.join(missing)}",
            )
        try:
            out = str(tool.fn(**args))
        except TypeError as exc:
            return ToolResult(status="error", error_code="bad_arguments",
                              retryable=True, hint=str(exc))
        except Exception as exc:                      # noqa: BLE001
            return ToolResult(status="error", error_code=type(exc).__name__,
                              retryable=False, hint=str(exc)[:300])
        truncated = len(out) > MAX_TOOL_OUTPUT
        return ToolResult(status="ok", content=out[:MAX_TOOL_OUTPUT],    ##из всего, что возвращает инструмент берем пока только часть [0: Max_Tool_Output]
                          truncated=truncated)




