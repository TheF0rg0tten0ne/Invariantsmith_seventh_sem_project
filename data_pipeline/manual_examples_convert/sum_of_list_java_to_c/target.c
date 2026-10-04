#include <stdio.h>

int main(void) {
    int nums[5] = {4, 8, 15, 16, 23};
    int total = 0;
    for (int i = 0; i < 5; i++) {
        total += nums[i];
    }
    printf("%d\n", total);
    return 0;
}
