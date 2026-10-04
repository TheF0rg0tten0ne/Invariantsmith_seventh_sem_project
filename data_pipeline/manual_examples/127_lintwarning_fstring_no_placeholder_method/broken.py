class Invoice:
    def __init__(self, total):
        self.total = total

    def summary(self):
        return f"Total due: total dollars"
