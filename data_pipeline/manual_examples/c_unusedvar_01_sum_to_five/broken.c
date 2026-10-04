#include <stdio.h>

int sum_to_five(void) {
    int i, total = 0;
    int scratch = 0;
    for (i = 1; i <= 5; i++) {
        total += i;
    }
    return total;
}

int main(void) {
    printf("%d\n", sum_to_five());
    return 0;
}
