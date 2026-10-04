#include <stdio.h>

typedef struct {
    int x;
    int y;
} Point;

Point make_point(int x, int y)
    Point p;
    p.x = x;
    p.y = y;
    return p;
}

int main(void) {
    Point p = make_point(3, 4);
    printf("Point(%d, %d)\n", p.x, p.y);
    return 0;
}
