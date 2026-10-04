def cached(func):
    store = {}

    def wrapper(*args):
        if args not in store:
            store[args] = func(*args)
        return store[args]
    return wrapper


@cached
def slow_square(x):
    return x * x
