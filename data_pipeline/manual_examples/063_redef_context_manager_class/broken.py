class Timer:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def __enter__(self):
        print("starting timer")
        return self
