def build_report(rows):
    def render_row(row):
        return f"{row.name}: {row.total}"
    return "\n".join(render_row(row) for row in rows)
