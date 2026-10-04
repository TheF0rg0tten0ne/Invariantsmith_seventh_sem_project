#include <stdio.h>

int temperature_alert(void) {
    int temp = 90;
    int last_reading = 0;
    return temp > 85 ? 1 : 0;
}

int main(void) {
    printf("%d\n", temperature_alert());
    return 0;
}
