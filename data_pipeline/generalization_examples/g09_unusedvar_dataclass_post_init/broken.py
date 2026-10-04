class Report:
    def __init__(self, rows):
        self.rows = rows
        row_count = len(rows)
        self.summary = f"{len(rows)} rows"
