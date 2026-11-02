from typing import Any
import hashlib
import json
from ..Budget import Budget
import os
from pathlib import Path
import time
from ..Tool.ToolsResult import ToolResult
from ..Debugging.Reply import Reply
from dotenv import load_dotenv

load_dotenv(dotenv_path="C:\\Users\\User\\Desktop\\ITMO\\Aiagentsfullcourse\\templates\\env\\.env.example")


RUNS_DIR = Path(os.environ.get("AGENT_RUNS_DIR", "../runs"))

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