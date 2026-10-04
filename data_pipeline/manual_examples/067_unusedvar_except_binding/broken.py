def safe_call(func, *args):
    try:
        return func(*args)
    except Exception as e:
        return None
