#include <stdio.h>

int apply_discount(void) {
    int price = 100;
    int discount_flag = 1;
    return price - 10;
}

int main(void) {
    printf("%d\n", apply_discount());
    return 0;
}
