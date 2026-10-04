#include <stdio.h>

int level_up(void) {
    int level = 1;
    level = level + 1;
    level = level * 2;
    return level;
}

int main(void) {
    printf("%d\n", level_up());
    return 0;
}
