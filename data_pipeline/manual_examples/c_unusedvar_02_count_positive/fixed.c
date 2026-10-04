#include <stdio.h>

int count_positive(void) {
    int count = 0;
    int nums[3] = {1, -2, 3};
    for (int i = 0; i < 3; i++) {
        if (nums[i] > 0) count++;
    }
    return count;
}

int main(void) {
    printf("%d\n", count_positive());
    return 0;
}
