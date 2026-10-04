#include <stdio.h>

int counter_increment(void) {
    int count = 0;
    count = count + 1;
    int count = count + 1;
    return count;
}

int main(void) {
    printf("%d\n", counter_increment());
    return 0;
}
