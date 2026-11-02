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
import sys
import time
from typing import Any
from .Task import Task
from .Budget import Budget
from dotenv import load_dotenv
from .Tool.ToolsResult import ToolResult
from .Tool.ToolImplementation import Tool, ToolRegistry
from .Debugging.Trace import Trace
from .Tool.Tools.Factorial import factorial
from .Tool.Tools.PythonInterpretator import apply_script
from .Tool.Tools.ReadFile import read_file
from .LLM.OpenRouterLLM import OpenRouterLLM
from .ValueObject import ModelAnswer


load_dotenv(dotenv_path="C:\\Users\\User\\Desktop\\ITMO\\Aiagentsfullcourse\\templates\\env\\.env.example")



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

test_history = []

def run(task: Task, tools: ToolRegistry, llm, trace: Trace) -> dict[str, Any]:
    budget = Budget(task=task)
    history: list[dict] = [{"role": "user", "content": task.prompt}]
    test_history = history
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
                print(history)
                return finish("no_progress", history, budget, trace)
            history.append(observation(
                "Пустой ответ. Выбери инструмент или дай итог."))
            continue

        # 4b. Финальный ответ - проверяем постусловие
        if not reply.tool_calls:
            ok, note = verify(task, reply.text)
            if ok:
                code = "done" if task.postcondition else "done_unverified"
                print(history)
                return finish(code, history, budget, trace, answer=reply.text)
            history.append(observation(f"Постусловие не выполнено: {note}"))
            continue

        history.append({"role": "assistant", "content": reply.text or None,
                        "tool_calls": reply.tool_calls})

        # 5. Действия
        for call in reply.tool_calls:
            fp = tools.fingerprint(call)
            if seen.count(fp) >= REPEAT_LIMIT:
                print(history)
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
        return task.postcondition(ModelAnswer(answer))
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

test_tool = Tool(
    name="python",
    description="Вызывает любой код, который ты напишешь, используется python интерпретатор, необходимо явно искомый ответ выводить в консоль, потому что реализация инструмента перехватывает вывод программы в консоль"
                "стоит выводить чистый код, без каких либо пояснений и кавычек в начале и конце, так же ты должен просто присылать текст скрипта, а инструмент самостоятельно создаст файлы выведет и тд",
    parameters={
        "type": "object",
        "properties": {"script": {"type": "str",
                             "description": "Скрипт, написанный на языке python"},
                       "run_id": {"type": "str",
                                  "descriptions":"run_id текущего вызова"}
                       },
        "required": ["script"],
        },
    fn=apply_script
)

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
        fn=factorial,
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
        fn=read_file,
    ),
    test_tool
])


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    print(__package__)
    ap = argparse.ArgumentParser(description="Модуль 01: минимальное ядро агента")
    ap.add_argument("--task", default="прочитай файл \"C:\\Users\\User\\Desktop\\test.txt\" и выведи в ответе, что там написано, так же если там написана какая-то математическая задача реши")
    ap.add_argument("--max-steps", type=int, default=16)
    ap.add_argument("--max-cost", type=float, default=0.50)
    args = ap.parse_args(argv)

    run_id = "r-" + hashlib.sha256(
        (args.task + str(time.time())).encode()).hexdigest()[:6]
    trace = Trace(run_id)
    # llm = OpenAICompatLLM() if args.live else FakeLLM()
    llm = OpenRouterLLM()
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
    print(f"История: \n{test_history}")
    return 0 if result["reason"] in {"done", "done_unverified"} else 1


if __name__ == "__main__":
    sys.exit(main())
