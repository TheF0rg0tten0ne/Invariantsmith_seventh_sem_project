#include <stdio.h>

const char *classify(int n) {
    if (n > 0) {
        return "positive";
    } else if (n < 0) {
        return "negative";
    }
    return "zero";
}

int main(void) {
    printf("%s\n", classify(-7));
    return 0;
}
