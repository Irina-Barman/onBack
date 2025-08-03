import os
from pathlib import Path

from dotenv import load_dotenv


def is_running_in_docker() -> bool:
    if os.getenv("DOCKER_ENV") == "1":
        return True
    try:
        with open("/proc/1/cgroup", "rt") as f:  # noqa PTH123
            return "docker" in f.read() or "kubepods" in f.read()
    except FileNotFoundError:
        return False


env_file = ".env" if os.getenv("DOCKER_ENV") == "1" else ".env.local"
dotenv_path = Path(__file__).resolve().parents[1] / env_file
load_dotenv(dotenv_path=dotenv_path, override=True)

from .app_factory import create_app  # noqa E402

__all__ = ["create_app"]
