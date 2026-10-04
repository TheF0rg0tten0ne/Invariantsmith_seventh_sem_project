#include <stdio.h>

int running_total(void) {
    int total = 10;
    total += 5;
    total = total + 1;
    return total;
}

int main(void) {
    printf("%d\n", running_total());
    return 0;
}
