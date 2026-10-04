from typing import Optional

_USERS = {}


def find_user(user_id: int) -> Optional[dict]:
    return lookup(user_id
