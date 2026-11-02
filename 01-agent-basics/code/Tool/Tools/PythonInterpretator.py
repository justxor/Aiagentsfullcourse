from pathlib import Path
import sys


def apply_script(script: str, run_id):
    path = Path(f"C:\\Users\\User\\Desktop\\ITMO\\Aiagentsfullcourse\\01-agent-basics\\files\\file{run_id}.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(script)
    import subprocess

    result = subprocess.run(
        [sys.executable, path],
        capture_output=True,
        text=True
    )

    return result.stdout