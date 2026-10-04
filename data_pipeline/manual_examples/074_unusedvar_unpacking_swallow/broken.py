def split_name(full_name):
    parts = full_name.split(" ", 1)
    first, rest = parts[0], parts[1] if len(parts) > 1 else ""
    return first
