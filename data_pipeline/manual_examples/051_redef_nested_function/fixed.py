def process(data):
    def clean(item):
        return item.strip().lower()

    return [clean(x) for x in data]
