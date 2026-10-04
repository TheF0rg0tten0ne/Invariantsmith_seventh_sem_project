#include <stdio.h>

int average(int nums[], int count) {
    int total = 0;
    for (int i = 0; i < count; i++) {
        total += nums[i];
    }
    return total / count;
}

int main(void) {
    int nums[4] = {10, 20, 30, 40};
    printf("%d\n", average(nums, 4));
    return 0;
}
