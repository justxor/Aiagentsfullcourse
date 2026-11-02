from ..Debugging.Reply import Reply

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

