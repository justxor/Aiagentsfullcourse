import os
import re
import uuid
from typing import Any
import json
from dataclasses import dataclass, field
from ..Debugging.Reply import Reply

# Жёсткие правила вывода — вшиваются в system, чтобы парсер мог
# надёжно вытащить tool_calls даже у моделей без native function-calling.
OUTPUT_RULES = """
ФОРМАТ ОТВЕТА (строго, без отклонений):

A) Финальный ответ (задача решена, инструменты не нужны):
   Пиши обычный текст. Не вызывай инструменты. Не оборачивай в JSON/XML.

B) Вызов инструмента(ов):
   Либо используй native tool_calls API (предпочтительно),
   либо выводи ТОЛЬКО следующий блок (без текста вокруг):

   <tool_calls>
   [{"name": "имя_инструмента", "arguments": {"ключ": значение}}]
   </tool_calls>

Правила аргументов:
- arguments — один JSON-объект, ключи = имена параметров из схемы.
- Типы: integer без кавычек, string в кавычках, boolean true/false.
- Обязательные параметры из required обязаны быть.
- Не выдумывай параметры, которых нет в схеме.
- Один шаг = один или несколько вызовов; после результата инструментов
  либо вызывай следующий инструмент, либо дай финальный ответ (вариант A).
- При ошибке инструмента НЕ повторяй тот же вызов с теми же arguments.
""".strip()


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = "fake"
    in_tokens: int = 0
    out_tokens: int = 0
    cost_usd: float = 0.0


def _normalize_messages(window: list[dict]) -> list[dict]:
    """Приводит history к OpenAI/OpenRouter-совместимым messages.

    - system/user/assistant/tool остаются.
    - tool_calls у assistant сериализуются в OpenAI-формат
      (arguments всегда строка JSON).
    - role=tool требует tool_call_id.
    """
    out: list[dict] = []
    for m in window:
        role = m.get("role", "user")
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for c in m["tool_calls"]:
                args = c.get("arguments", {})
                if not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False)
                calls.append({
                    "id": c.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": c["name"],
                        "arguments": args,
                    },
                })
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": calls,
            }
            out.append(msg)
            continue

        if role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id") or m.get("name", "tool"),
                "name": m.get("name"),
                "content": m.get("content", "") or "",
            })
            continue

        # system / user / обычный assistant
        content = m.get("content")
        if content is None:
            content = ""
        out.append({"role": role, "content": content})
    return out


def _parse_args(raw: Any) -> dict[str, Any]:
    """Аргументы → dict. Терпит строку JSON, уже-dict, пустое."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else {"_raw": parsed}
        except json.JSONDecodeError:
            # Частая поломка: одинарные кавычки / trailing comma
            try:
                fixed = s.replace("'", '"')
                fixed = re.sub(r",\s*}", "}", fixed)
                fixed = re.sub(r",\s*]", "]", fixed)
                parsed = json.loads(fixed)
                return parsed if isinstance(parsed, dict) else {"_raw": parsed}
            except Exception:
                return {"_unparsed": s}
    return {"_raw": raw}


class OpenRouterLLM:
    """Адаптер OpenRouter: OpenAI-совместимые messages + tools.

    Парсеры:
      - tools_parser  — native tool_calls ИЛИ fallback <tool_calls>...</tool_calls>
      - content_parser — чистый текст ответа (без блоков tool_calls)
      - tokens_parser — usage из response
    """

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get(
            "OPENROUTER_AGENT_MODEL", "nvidia/nemotron-3.5-super-vl:free"
        )
        self.api_key = (
            os.environ.get("OPENAI_API_KEY", "No_Key")
        )
        self.price_in = float(os.environ.get("PRICE_IN_PER_MTOK", "0.15"))
        self.price_out = float(os.environ.get("PRICE_OUT_PER_MTOK", "0.60"))
        self.base_url = os.environ.get(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions"
        )
        # Если модель не умеет native tools — форсим текстовый протокол.
        self.force_text_tools = os.environ.get("FORCE_TEXT_TOOLS", "").lower() in {
            "1", "true", "yes"
        }

    # ------------------------------------------------------------------ #
    # Парсеры
    # ------------------------------------------------------------------ #

    def content_parser(self, message: dict[str, Any]) -> str:
        """Текст финального ответа. Убирает fallback-блоки tool_calls."""
        content = message.get("content")
        if content is None:
            return ""
        if not isinstance(content, str):
            # multimodal: [{"type":"text","text":"..."}]
            if isinstance(content, list):
                parts = [
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = "".join(parts)
            else:
                content = str(content)
        # вырезаем <tool_calls>...</tool_calls>, чтобы не дублировать в answer
        content = re.sub(
            r"<tool_calls>.*?</tool_calls>",
            "",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()
        return content

    def tokens_parser(self, response: dict[str, Any]) -> dict[str, int]:
        """usage → prompt/completion tokens. Безопасно к отсутствию полей."""
        u = response.get("usage") or {}
        return {
            "prompt_tokens": int(u.get("prompt_tokens") or u.get("input_tokens") or 0),
            "completion_tokens": int(
                u.get("completion_tokens") or u.get("output_tokens") or 0
            ),
            "total_tokens": int(u.get("total_tokens") or 0),
            # OpenRouter иногда отдаёт cost прямо в usage
            "cost": float(u.get("cost") or 0.0),
        }

    def tools_parser(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """Native tool_calls → наш формат; иначе ищем <tool_calls> в content."""
        calls: list[dict[str, Any]] = []

        # 1) Native OpenAI/OpenRouter tool_calls
        for tc in message.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            if not name:
                continue
            args = _parse_args(fn.get("arguments") if "arguments" in fn else tc.get("arguments"))
            calls.append({
                "name": name,
                "arguments": args,
                "id": tc.get("id") or f"call_{uuid.uuid4().hex[:12]}",
            })
        if calls:
            return calls

        # 2) Fallback: текстовый протокол <tool_calls>[...]</tool_calls>
        content = message.get("content") or ""
        if not isinstance(content, str):
            return []
        m = re.search(
            r"<tool_calls>\s*(.*?)\s*</tool_calls>",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not m:
            # запасной паттерн: голый JSON-массив с "name" и "arguments"
            m2 = re.search(
                r'\[\s*\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:',
                content,
            )
            if not m2:
                return []
            # пытаемся вырезать ближайший JSON-массив
            start = content.find("[", m2.start())
            depth = 0
            end = -1
            for i, ch in enumerate(content[start:], start):
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end < 0:
                return []
            raw_list = content[start:end]
        else:
            raw_list = m.group(1).strip()

        try:
            items = json.loads(raw_list)
        except json.JSONDecodeError:
            try:
                fixed = raw_list.replace("'", '"')
                fixed = re.sub(r",\s*}", "}", fixed)
                fixed = re.sub(r",\s*]", "]", fixed)
                items = json.loads(fixed)
            except Exception:
                return []

        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return []

        for item in items:
            if not isinstance(item, dict) or "name" not in item:
                continue
            calls.append({
                "name": item["name"],
                "arguments": _parse_args(item.get("arguments")),
                "id": item.get("id") or f"call_{uuid.uuid4().hex[:12]}",
            })
        return calls

    # ------------------------------------------------------------------ #
    # chat
    # ------------------------------------------------------------------ #

    def chat(self, window: list[dict], tools: list[dict]) -> Reply:
        import requests

        messages = _normalize_messages(window)

        # Жёсткие правила вывода — в начало system (или отдельным system).
        if messages and messages[0].get("role") == "system":
            messages[0] = {
                "role": "system",
                "content": (messages[0].get("content") or "") + "\n\n" + OUTPUT_RULES,
            }
        else:
            messages.insert(0, {"role": "system", "content": OUTPUT_RULES})

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }

        # Native tools, если не форсим текстовый протокол
        if tools and not self.force_text_tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        elif tools and self.force_text_tools:
            # В текстовом режиме схема инструментов тоже в system,
            # чтобы модель знала имена/параметры.
            schema_hint = (
                "Доступные инструменты (JSON Schema):\n"
                + json.dumps(tools, ensure_ascii=False, indent=2)
            )
            messages[0]["content"] = messages[0]["content"] + "\n\n" + schema_hint

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", "https://localhost"),
            "X-Title": os.environ.get("OPENROUTER_TITLE", "agent-basics"),
        }

        try:
            resp = requests.post(
                self.base_url,
                headers=headers,
                data=json.dumps(body)
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            # Ошибка сети/API → пустой Reply с текстом-ошибкой,
            # цикл увидит empty/answer и сможет остановиться по бюджету.
            return Reply(
                text=f"[openrouter_error] {type(exc).__name__}: {exc}",
                model=self.model,
            )

        if "error" in data and not data.get("choices"):
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return Reply(text=f"[openrouter_error] {msg}", model=self.model)

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}

        text = self.content_parser(message)
        calls = self.tools_parser(message)
        usage = self.tokens_parser(data)

        in_tok = usage["prompt_tokens"]
        out_tok = usage["completion_tokens"]
        # Если OpenRouter отдал cost — берём его, иначе считаем по прайсу.
        cost = usage.get("cost") or 0.0
        if not cost:
            cost = in_tok / 1e6 * self.price_in + out_tok / 1e6 * self.price_out

        return Reply(
            text=text,
            tool_calls=calls,
            model=data.get("model") or self.model,
            in_tokens=in_tok,
            out_tokens=out_tok,
            cost_usd=float(cost),
        )