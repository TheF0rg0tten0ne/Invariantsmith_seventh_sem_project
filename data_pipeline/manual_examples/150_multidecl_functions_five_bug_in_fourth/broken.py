def is_positive(n):
    return n > 0


def is_negative(n):
    return n < 0


def is_zero(n):
    return n == 0


def sign_label(n):
    if n > 0:
        return "positive"
    if n < 0:
        return "negative"
    return zero_label


def clamp_sign(n):
    if n > 0:
        return 1
    if n < 0:
        return -1
    return 0
