def calculate_total(items, tax=0):
    total = 0
    for item in items:
        total += item.price
    return total + tax
