#include <stdio.h>

long factorial(int n) {
    long result = 1;
    for (int i = 2; i <= n; i++) {
        result *= i;
    }
    return result;
}

int main(void) {
    printf("%ld\n", factorial(6));
    return 0;
}
