import time


def timestamped(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


@timestamped
def compute():
    return 42
