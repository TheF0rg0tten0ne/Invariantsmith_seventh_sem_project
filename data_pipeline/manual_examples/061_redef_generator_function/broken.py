def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def chunks(items, size):
    for i in range(0, len(items), size):
        yield list(items[i:i + size])
