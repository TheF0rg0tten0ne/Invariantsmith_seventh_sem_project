#include <stdio.h>

void apply_tax(int amount, int rate) {
    printf("%d\n", amount + amount * rate / 100);
}

int main(void) {
    return 0;
}
