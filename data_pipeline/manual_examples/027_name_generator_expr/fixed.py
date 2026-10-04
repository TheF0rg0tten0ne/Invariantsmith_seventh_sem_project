def total_valid(entries):
    return sum(e.score for e in entries if e.active)
