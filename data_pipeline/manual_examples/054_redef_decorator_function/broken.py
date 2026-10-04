def require_auth(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


def require_auth(func):
    def wrapper(*args, **kwargs):
        print("checking auth")
        return func(*args, **kwargs)
    return wrapper
