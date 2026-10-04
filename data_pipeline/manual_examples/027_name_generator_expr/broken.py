def total_valid(entries):
    return sum(score(e) for e in entries if e.active)
