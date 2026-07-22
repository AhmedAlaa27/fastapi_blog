import hashlib
import json
from datetime import datetime


def post_detail_key(post_id: int) -> str:
    return f"posts:{post_id}"


def post_list_key(
    skip: int,
    limit: int,
    search: str | None,
    author: int | None,
    created_after: datetime | None,
    created_before: datetime | None,
    sort: str,
) -> str:
    params = {
        "skip": skip,
        "limit": limit,
        "search": search,
        "author": author,
        "created_after": created_after.isoformat() if created_after else None,
        "created_before": created_before.isoformat() if created_before else None,
        "sort": sort,
    }
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    return f"posts:list:{digest}"


def post_list_pattern() -> str:
    return "posts:list:*"
