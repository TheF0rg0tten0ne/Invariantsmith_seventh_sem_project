class Timer:
    def __exit__(self, *exc_info):
        return False

    def __enter__(self):
        print("starting timer")
        return self
