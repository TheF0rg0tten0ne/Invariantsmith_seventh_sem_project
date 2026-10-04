#include <stdio.h>

int page_number(void) {
    int page = 1;
    page = page + 1;
    page = page + 1;
    return page;
}

int main(void) {
    printf("%d\n", page_number());
    return 0;
}
