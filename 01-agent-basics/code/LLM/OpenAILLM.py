import os
import json
from ..Debugging.Reply import Reply

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