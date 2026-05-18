from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path | str, *, override: bool = False) -> bool:
    """
    Load a small .env file without making python-dotenv mandatory.
    """
    try:
        from dotenv import load_dotenv as real_load_dotenv  # type: ignore

        return bool(real_load_dotenv(path, override=override))
    except ModuleNotFoundError:
        env_path = Path(path)
        if not env_path.exists():
            return False
        for line in env_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = value
        return True
