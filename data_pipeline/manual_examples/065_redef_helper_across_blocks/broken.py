def build_pipeline(steps):
    def run(data):
        for step in steps:
            data = step(data)
        return data

    if not steps:
        def run(data):
            return data

    return run
