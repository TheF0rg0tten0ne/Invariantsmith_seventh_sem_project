def logged(func):
    def wrapper(*args, **kwargs):
        call_count = 0
        return func(*args, **kwargs)
    return wrapper
