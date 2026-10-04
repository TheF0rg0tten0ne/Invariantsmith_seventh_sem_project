def classify(status):
    match status:
        case 200:
            return "ok"
        case 404:
            return "not found"
        case _:
            return "unknown"
