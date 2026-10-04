def status_label(code):
    if code == 200:
        return "ok"
    if code == 404:
        return "not found"
    return "error"
