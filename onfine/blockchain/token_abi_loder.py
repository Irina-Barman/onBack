import json
from functools import lru_cache
from pathlib import Path

ABI_PATH = Path(__file__).resolve().parents[1] / "abis" / "default_abi.json"


@lru_cache(maxsize=1)
def load_abi() -> list:  # noqa D103
    if not ABI_PATH.exists():
        raise FileNotFoundError(f"ABI файл не найден: {ABI_PATH}")
    with ABI_PATH.open() as f:
        return json.load(f)


@lru_cache(maxsize=1)
def abi_by_name() -> dict:  # noqa D103
    return {item["name"]: item for item in load_abi() if "name" in item}
