#include <stdio.h>

int balance_after_fee(void) {
    int balance = 500;
    balance -= 20;
    balance = balance - 5;
    return balance;
}

int main(void) {
    printf("%d\n", balance_after_fee());
    return 0;
}
