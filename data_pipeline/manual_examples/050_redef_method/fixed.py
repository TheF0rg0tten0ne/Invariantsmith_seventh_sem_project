class Parser:
    def parse(self, text):
        return [t.strip() for t in text.split()]
