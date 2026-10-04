#include <stdio.h>

double celsius_to_fahrenheit(double c) {
    return c * 9.0 / 5.0 + 32.0;
}

int main(void) {
    printf("%g\n", celsius_to_fahrenheit(21));
    return 0;
}
