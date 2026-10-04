#include <stdio.h>

int main(void) {
    int player_level = 1;
    int *level = &player_level;
    printf("%d\n", *level);
    return 0;
}
