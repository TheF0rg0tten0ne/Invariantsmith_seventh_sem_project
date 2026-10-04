#include <stdio.h>

int is_even(int n) {
    return n % 2 == 0;
}

int main(void) {
    printf("%d\n", is_even(5));
    return 0;
}
