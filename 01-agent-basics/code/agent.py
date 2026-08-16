"""
Модуль 01. Минимальное ядро агента: цикл, бюджеты, стоп-условия, трейс.

Запуск без ключей и без сети (детерминированная фиктивная модель):
    python 01-agent-basics/code/agent.py

Запуск с реальной моделью:
    export OPENAI_API_KEY=...            # или совместимый провайдер
    python 01-agent-basics/code/agent.py --live --task "посчитай 17!"

Принципы, заложенные в этот файл:
  1. Границы проверяются ДО траты денег.
  2. Ошибка инструмента - это данные, а не исключение.
  3. history (правда о прогоне) и window (что отправлено модели) разделены.
  4. Каждый выход из цикла имеет код причины.
  5. Трейс пишется всегда, в JSONL, по одной записи на строку.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

RUNS_DIR = Path(os.environ.get("AGENT_RUNS_DIR", "runs"))


# --------------------------------------------------------------------------- #
# Задача и бюджеты
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Task:
    """Иммутабельна: агент не имеет права переписать задачу под себя."""
    prompt: str
    postcondition: Callable[[str], tuple[bool, str]] | None = None
    max_steps: int = 16
    max_seconds: float = 300.0
    max_tokens: int = 200_000
    max_cost_usd: float = 0.50


@dataclass
class Budget:
    task: Task
    started: float = field(default_factory=time.monotonic)
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    empty_steps: int = 0
    warned: bool = False

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def exceeded(self) -> str | None:
        if self.steps >= self.task.max_steps:
            return "budget_steps"
        if self.elapsed() >= self.task.max_seconds:
            return "budget_time"
        if self.tokens >= self.task.max_tokens:
            return "budget_tokens"
        if self.cost_usd >= self.task.max_cost_usd:
            return "budget_cost"
        return None

    def ratios(self) -> dict[str, float]:
        return {
            "steps": self.steps / max(self.task.max_steps, 1),
            "time": self.elapsed() / max(self.task.max_seconds, 1e-9),
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


# --------------------------------------------------------------------------- #
# Инструменты: ошибка возвращается как данные
# --------------------------------------------------------------------------- #

MAX_TOOL_OUTPUT = 4000  # символов; всё лишнее обрезается с флагом truncated


@dataclass
class ToolResult:
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


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., str]


class ToolRegistry:
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
        missing = [k for k in tool.parameters.get("required", []) if k not in args]
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
        return ToolResult(status="ok", content=out[:MAX_TOOL_OUTPUT],
                          truncated=truncated)


# --------------------------------------------------------------------------- #
# Трейс: JSONL, всегда включён
# --------------------------------------------------------------------------- #

class Trace:
    def __init__(self, run_id: str) -> None:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.path = RUNS_DIR / f"{run_id}.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")

    def _write(self, rec: dict[str, Any]) -> None:
        rec = {"run_id": self.run_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                          time.gmtime()), **rec}
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()

    @staticmethod
    def _hash(obj: Any) -> str:
        blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def step(self, n: int, window: list[dict], reply: "Reply", budget: Budget,
             latency_ms: int) -> None:
        self._write({
            "t": "step", "step": n, "model": reply.model,
            "in_tokens": reply.in_tokens, "out_tokens": reply.out_tokens,
            "cost_usd": round(reply.cost_usd, 6), "latency_ms": latency_ms,
            "window_hash": self._hash(window), "window_msgs": len(window),
            "decision": "tool_call" if reply.tool_calls else
                        ("answer" if reply.text.strip() else "empty"),
            "tools": [c["name"] for c in reply.tool_calls],
            "budget": budget.snapshot(),
        })

    def tool(self, n: int, call: dict, res: ToolResult, ms: int) -> None:
        self._write({
            "t": "tool", "step": n, "tool": call["name"],
            "args": call.get("arguments", {}), "status": res.status,
            "error_code": res.error_code, "retryable": res.retryable,
            "hint": res.hint, "truncated": res.truncated,
            "bytes_out": len(res.content), "duration_ms": ms,
        })

    def finish(self, reason: str, budget: Budget, answer: str | None) -> None:
        self._write({"t": "finish", "reason": reason,
                     "budget": budget.snapshot(),
                     "answer_chars": len(answer or "")})
        self._fh.close()


# --------------------------------------------------------------------------- #
# Модель: тонкий адаптер. Меняется один класс, агент не трогается.
# --------------------------------------------------------------------------- #

@dataclass
class Reply:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = "fake"
    in_tokens: int = 0
    out_tokens: int = 0
    cost_usd: float = 0.0


class FakeLLM:
    """Детерминированная модель для тестов цикла: без сети и без денег.

    Сценарий: сначала пробует factorial с неверным аргументом (проверяем,
    что ошибка приходит как данные), затем с верным, затем отвечает.
    """
    model = "fake-deterministic"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, window: list[dict], tools: list[dict]) -> Reply:
        self.calls += 1
        in_tokens = sum(len(str(m)) for m in window) // 4
        if self.calls == 1:
            return Reply(tool_calls=[{"name": "factorial",
                                      "arguments": {"n": -5}}],
                         model=self.model, in_tokens=in_tokens, out_tokens=20,
                         cost_usd=in_tokens * 1.5e-7 + 20 * 6e-7)
        if self.calls == 2:
            return Reply(tool_calls=[{"name": "factorial",
                                      "arguments": {"n": 17}}],
                         model=self.model, in_tokens=in_tokens, out_tokens=20,
                         cost_usd=in_tokens * 1.5e-7 + 20 * 6e-7)
        last = ""
        for msg in reversed(window):
            if msg.get("role") == "tool":
                last = msg.get("content", "")
                break
        return Reply(text=f"Готово. Результат инструмента: {last}",
                     model=self.model, in_tokens=in_tokens, out_tokens=40,
                     cost_usd=in_tokens * 1.5e-7 + 40 * 6e-7)


class OpenAICompatLLM:
    """Реальный провайдер. Специально в 30 строк: адаптер, а не фреймворк."""

    def __init__(self, model: str | None = None) -> None:
        from openai import OpenAI          # импорт внутри: не нужен для тестов
        self.client = OpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None)
        self.model = model or os.environ.get("AGENT_MODEL", "gpt-4o-mini")
        self.price_in = float(os.environ.get("PRICE_IN_PER_MTOK", "0.15"))
        self.price_out = float(os.environ.get("PRICE_OUT_PER_MTOK", "0.60"))

    def chat(self, window: list[dict], tools: list[dict]) -> Reply:
        resp = self.client.chat.completions.create(
            model=self.model, messages=window, tools=tools, temperature=0,
        )
        msg = resp.choices[0].message
        calls = [
            {"name": c.function.name,
             "arguments": json.loads(c.function.arguments or "{}"),
             "id": c.id}
            for c in (msg.tool_calls or [])
        ]
        u = resp.usage
        return Reply(
            text=msg.content or "", tool_calls=calls, model=self.model,
            in_tokens=u.prompt_tokens, out_tokens=u.completion_tokens,
            cost_usd=u.prompt_tokens / 1e6 * self.price_in
                     + u.completion_tokens / 1e6 * self.price_out,
        )


# --------------------------------------------------------------------------- #
# Сборка окна: единственное место, куда позже встроится компакция (модуль 04)
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """Ты инженерный агент. Работай по шагам.

Правила:
1. Если нужно действие - вызывай инструмент, не описывай его словами.
2. Результат инструмента - единственный источник фактов. Не выдумывай.
3. Если инструмент вернул ОШИБКУ, не повторяй тот же вызов с теми же
   аргументами: измени аргументы или выбери другой путь.
4. Когда задача решена, дай финальный ответ без вызова инструментов.
5. Если данных не хватает и получить их нечем - скажи об этом прямо.
"""


def build_window(task: Task, history: list[dict], warning: str | None) -> list[dict]:
    """Пока просто: system + вся история. В модуле 04 здесь появится
    компакция, приоритизация и пометка недоверенного контента."""
    window: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if warning:
        window.append({"role": "system", "content": warning})
    window.extend(history)
    return window


def observation(text: str) -> dict[str, str]:
    return {"role": "user", "content": f"[наблюдение] {text}"}


def tool_message(call: dict, res: ToolResult) -> dict[str, Any]:
    return {"role": "tool", "name": call["name"],
            "tool_call_id": call.get("id", call["name"]),
            "content": res.to_model()}


# --------------------------------------------------------------------------- #
# Цикл
# --------------------------------------------------------------------------- #

EMPTY_LIMIT = 2          # сколько пустых шагов терпим
REPEAT_LIMIT = 3         # сколько одинаковых вызовов терпим


def run(task: Task, tools: ToolRegistry, llm, trace: Trace) -> dict[str, Any]:
    budget = Budget(task=task)
    history: list[dict] = [{"role": "user", "content": task.prompt}]
    seen: list[str] = []

    while True:
        # 1. Границы - до траты денег
        reason = budget.exceeded()
        if reason:
            return finish(reason, history, budget, trace)

        # 2. Наблюдение
        window = build_window(task, history, budget.soft_warning())

        # 3. Решение
        budget.steps += 1
        t0 = time.monotonic()
        reply = llm.chat(window, tools.schemas())
        latency_ms = int((time.monotonic() - t0) * 1000)
        budget.tokens += reply.in_tokens + reply.out_tokens
        budget.cost_usd += reply.cost_usd
        trace.step(budget.steps, window, reply, budget, latency_ms)

        # 4a. Пустой шаг
        if not reply.tool_calls and not reply.text.strip():
            budget.empty_steps += 1
            if budget.empty_steps > EMPTY_LIMIT:
                return finish("no_progress", history, budget, trace)
            history.append(observation(
                "Пустой ответ. Выбери инструмент или дай итог."))
            continue

        # 4b. Финальный ответ - проверяем постусловие
        if not reply.tool_calls:
            ok, note = verify(task, reply.text)
            if ok:
                code = "done" if task.postcondition else "done_unverified"
                return finish(code, history, budget, trace, answer=reply.text)
            history.append(observation(f"Постусловие не выполнено: {note}"))
            continue

        history.append({"role": "assistant", "content": reply.text or None,
                        "tool_calls": reply.tool_calls})

        # 5. Действия
        for call in reply.tool_calls:
            fp = tools.fingerprint(call)
            if seen.count(fp) >= REPEAT_LIMIT:
                return finish("repeated_action", history, budget, trace)
            seen.append(fp)

            t1 = time.monotonic()
            res = tools.invoke(call)
            trace.tool(budget.steps, call, res, int((time.monotonic() - t1) * 1000))
            history.append(tool_message(call, res))


def verify(task: Task, answer: str) -> tuple[bool, str]:
    if task.postcondition is None:
        return True, "постусловия нет"
    try:
        return task.postcondition(answer)
    except Exception as exc:                          # noqa: BLE001
        return False, f"проверка упала: {exc}"


def finish(reason: str, history: list[dict], budget: Budget, trace: Trace,
           answer: str | None = None) -> dict[str, Any]:
    trace.finish(reason, budget, answer)
    return {
        "reason": reason,
        "answer": answer,
        "steps": budget.steps,
        "tokens": budget.tokens,
        "cost_usd": round(budget.cost_usd, 6),
        "seconds": round(budget.elapsed(), 2),
        "history_len": len(history),
        "trace": str(trace.path),
    }


# --------------------------------------------------------------------------- #
# Демонстрационные инструменты
# --------------------------------------------------------------------------- #

def _factorial(n: int) -> str:
    n = int(n)
    if n < 0:
        raise ValueError("факториал определён только для n >= 0")
    if n > 2000:
        raise ValueError("n слишком велико, предел 2000")
    return str(math.factorial(n))


def _read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        siblings = sorted(x.name for x in (p.parent if p.parent.exists()
                                           else Path(".")).iterdir())[:10]
        raise FileNotFoundError("файла нет; рядом: " + ", ".join(siblings))
    return p.read_text(encoding="utf-8", errors="replace")


DEMO_TOOLS = ToolRegistry([
    Tool(
        name="factorial",
        description=("Точно вычисляет факториал целого неотрицательного n. "
                     "Возвращает десятичную запись числа. Предел n = 2000. "
                     "Используй вместо самостоятельного счёта в уме."),
        parameters={
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 0,
                                 "maximum": 2000,
                                 "description": "неотрицательное целое"}},
            "required": ["n"],
        },
        fn=_factorial,
    ),
    Tool(
        name="read_file",
        description=("Читает текстовый файл целиком и возвращает содержимое. "
                     "Путь относительно корня проекта. Если файла нет, "
                     "вернёт ошибку со списком соседних файлов."),
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string",
                                    "description": "относительный путь"}},
            "required": ["path"],
        },
        fn=_read_file,
    ),
])


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Модуль 01: минимальное ядро агента")
    ap.add_argument("--task", default="Посчитай 17 факториал через инструмент.")
    ap.add_argument("--live", action="store_true",
                    help="использовать реального провайдера вместо FakeLLM")
    ap.add_argument("--max-steps", type=int, default=16)
    ap.add_argument("--max-cost", type=float, default=0.50)
    args = ap.parse_args(argv)

    run_id = "r-" + hashlib.sha256(
        (args.task + str(time.time())).encode()).hexdigest()[:6]
    trace = Trace(run_id)
    llm = OpenAICompatLLM() if args.live else FakeLLM()
    task = Task(prompt=args.task, max_steps=args.max_steps,
                max_cost_usd=args.max_cost)

    result = run(task, DEMO_TOOLS, llm, trace)

    print("=" * 62)
    print(f"run_id:   {run_id}")
    print(f"причина:  {result['reason']}")
    print(f"шаги:     {result['steps']}")
    print(f"токены:   {result['tokens']}")
    print(f"стоимость:{result['cost_usd']} USD")
    print(f"время:    {result['seconds']} c")
    print(f"трейс:    {result['trace']}")
    print("-" * 62)
    print(result["answer"] or "(ответа нет)")
    print("=" * 62)
    return 0 if result["reason"] in {"done", "done_unverified"} else 1


if __name__ == "__main__":
    sys.exit(main())
