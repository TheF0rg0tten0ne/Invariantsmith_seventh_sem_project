def safe_open(path):
    try
        return open(path)
    except FileNotFoundError:
        return None
