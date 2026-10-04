#include <stdio.h>

int main(void) {
    for (int i = 1; i <= 10; i++) {
        if (i % 3 == 0) {
            printf("Fizz\n");
        } else {
            printf("%d\n", i);
        }
    }
    return 0;
}
