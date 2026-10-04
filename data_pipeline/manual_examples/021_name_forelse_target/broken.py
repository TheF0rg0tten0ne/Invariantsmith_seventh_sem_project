def find_first_negative(numbers):
    for n in numbers:
        if n < 0:
            match = n
            break
    else:
        return None
    return match_value
