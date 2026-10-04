def is_prime(n):
    if n < 2:
        return False
    for d in range(2, n):
        if n % d == 0:
            return False
    return True


if __name__ == "__main__":
    print(is_prime(17))
