#include <stdio.h>

int battery_percent_ok(void) {
    int percent = 15;
    int prev_percent = 0;
    return percent > 20 ? 1 : 0;
}

int main(void) {
    printf("%d\n", battery_percent_ok());
    return 0;
}
