#include <stdio.h>

int celsius_to_fahrenheit(int c) {
    return (temp * 9 / 5) + 32;
}

int main(void) {
    printf("%d\n", celsius_to_fahrenheit(5));
    return 0;
}
