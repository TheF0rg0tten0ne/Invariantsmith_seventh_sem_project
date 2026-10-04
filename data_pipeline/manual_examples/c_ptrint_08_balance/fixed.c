#include <stdio.h>

int main(void) {
    int account_balance = 250;
    int *balance = &account_balance;
    printf("%d\n", *balance);
    return 0;
}
