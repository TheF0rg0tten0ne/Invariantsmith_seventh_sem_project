def positive_only(func):
    def wrapper(x):
        if x < 0:
            raise ValueError("must be non-negative")
        return func(x)
    return wrapper
