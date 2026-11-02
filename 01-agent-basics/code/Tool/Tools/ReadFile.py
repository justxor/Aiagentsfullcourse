from pathlib import Path


def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        siblings = sorted(x.name for x in (p.parent if p.parent.exists()
                                           else Path(".")).iterdir())[:10]
        raise FileNotFoundError("файла нет; рядом: " + ", ".join(siblings))
    return p.read_text(encoding="utf-8", errors="replace")