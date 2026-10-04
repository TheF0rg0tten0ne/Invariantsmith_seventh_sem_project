def normalize(text)
    return text.strip().lower()


def batch_normalize(texts):
    return [normalize(t) for t in texts]
