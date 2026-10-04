#include <stdio.h>

const char *day_name(int day) {
    switch (day) {
        case 1: return "Monday";
        case 2: return "Tuesday";
        case 3: return "Wednesday";
        default: return "Unknown";
    }
}

int main(void) {
    printf("Day 2 is %s\n", day_name(2));
    return 0;
}
