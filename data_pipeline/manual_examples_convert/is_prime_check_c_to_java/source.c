#include <stdio.h>
#include <stdbool.h>

bool is_prime(int n) {
    if (n < 2) {
        return false;
    }
    for (int d = 2; d < n; d++) {
        if (n % d == 0) {
            return false;
        }
    }
    return true;
}

int main(void) {
    printf("%s\n", is_prime(17) ? "True" : "False");
    return 0;
}
