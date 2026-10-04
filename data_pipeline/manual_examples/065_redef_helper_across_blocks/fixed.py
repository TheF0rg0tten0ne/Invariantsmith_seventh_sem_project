def build_pipeline(steps):
    def run(data):
        for step in steps:
            data = step(data)
        return data

    return run
