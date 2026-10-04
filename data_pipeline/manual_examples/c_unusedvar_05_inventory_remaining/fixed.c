#include <stdio.h>

int inventory_remaining(void) {
    int stock = 40, sold = 12;
    return stock - sold;
}

int main(void) {
    printf("%d\n", inventory_remaining());
    return 0;
}
