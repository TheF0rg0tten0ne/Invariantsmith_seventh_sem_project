from typing import Optional

_USERS = {}


def find_user(user_id: int) -> Optional[dict]:
    return _USERS.get(user_id)
