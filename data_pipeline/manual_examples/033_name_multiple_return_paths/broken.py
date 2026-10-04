def status_label(code):
    if code == 200:
        return "ok"
    if code == 404:
        return not_found_label
    return "error"
