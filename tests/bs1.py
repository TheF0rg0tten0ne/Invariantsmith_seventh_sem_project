# A simple, correct Python script

def main():
    x = 10
    if x > 5:
        print("X is greater than 5")
    else:
        print("X is small")

    for i in range(5):
        print(i)

    # Controlled loop with break
    count = 0
    while True:
        print("Loop iteration:", count)
        count += 1
        if count == 3:
            break

if __name__ == "__main__":
    main()
