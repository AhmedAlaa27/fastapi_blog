import json
from typing import Any


def serialize(value: Any) -> str:
    return json.dumps(value)


def deserialize(raw: str) -> Any:
    return json.loads(raw)
