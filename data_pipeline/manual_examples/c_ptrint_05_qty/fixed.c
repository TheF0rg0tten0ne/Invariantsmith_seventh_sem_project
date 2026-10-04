#include <stdio.h>

int main(void) {
    int item_qty = 7;
    int *qty = &item_qty;
    printf("%d\n", *qty);
    return 0;
}
