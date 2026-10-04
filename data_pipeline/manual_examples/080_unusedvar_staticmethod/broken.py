class PathHelper:
    @staticmethod
    def join(base, *parts):
        separator = "/"
        return "/".join([base, *parts])
