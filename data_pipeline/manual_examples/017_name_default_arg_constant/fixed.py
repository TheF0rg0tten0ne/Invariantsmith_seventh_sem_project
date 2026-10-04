MAX_ALLOWED = 100


def clamp(value):
    return max(0, min(value, MAX_ALLOWED))
