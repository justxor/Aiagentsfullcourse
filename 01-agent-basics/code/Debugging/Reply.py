from dataclasses import dataclass, field
from typing import Any

@dataclass
class Reply:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = "fake"
    in_tokens: int = 0
    out_tokens: int = 0
    cost_usd: float = 0.0