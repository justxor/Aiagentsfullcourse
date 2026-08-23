from pathlib import Path
import os
import re

def load_env_file(env_path: str = ".env") -> None:
    """Load environment variables from .env file without external dependencies.
    
    Simple parser that handles:
    - KEY=value
    - KEY="value"
    - KEY='value'
    - Comments starting with #
    """
    env_file = Path(env_path)
    if not env_file.exists():
        return
    
    content = env_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        
        # Parse KEY=value
        match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if match:
            key = match.group(1)
            value = match.group(2).strip()
            
            # Remove quotes
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            
            # Only set if not already set
            if key not in os.environ:
                os.environ[key] = value


# Load .env file if it exists
load_env_file()