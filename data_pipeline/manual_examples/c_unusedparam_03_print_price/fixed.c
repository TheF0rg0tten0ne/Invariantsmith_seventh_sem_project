#include <stdio.h>

void print_price(int cents, int with_symbol) {
    printf(with_symbol ? "$%d\n" : "%d\n", cents);
}

int main(void) {
    return 0;
}
