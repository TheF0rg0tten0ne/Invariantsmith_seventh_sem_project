class ReportBuilder:
    def __init__(self, rows):
        self.rows = rows

    def header(self):
        return "Report"

    def header(self):
        return "Monthly Report"

    def footer(self):
        return f"{len(self.rows)} rows"
