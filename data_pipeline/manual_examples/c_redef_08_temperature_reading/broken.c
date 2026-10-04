#include <stdio.h>

int temperature_reading(void) {
    int temp = 20;
    temp = temp + 2;
    int temp = temp - 1;
    return temp;
}

int main(void) {
    printf("%d\n", temperature_reading());
    return 0;
}
