class PathHelper:
    @staticmethod
    def join(base, *parts):
        return "/".join([base, *parts])
