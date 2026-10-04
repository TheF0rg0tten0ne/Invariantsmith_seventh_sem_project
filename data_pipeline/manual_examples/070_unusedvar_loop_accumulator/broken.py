def count_valid(records):
    valid_count = 0
    debug_snapshot = list(records)
    for record in records:
        valid_count += 1
    return valid_count
