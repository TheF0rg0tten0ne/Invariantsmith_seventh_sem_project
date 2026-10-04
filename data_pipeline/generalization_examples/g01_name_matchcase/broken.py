def classify(status):
    match status:
        case 200:
            return "ok"
        case 404:
            return missing_label
        case _:
            return "unknown"
