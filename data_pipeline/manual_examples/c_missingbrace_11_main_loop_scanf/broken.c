#include <stdio.h>

int main()
    int count, sum = 0;
    printf("How many numbers? ");
    scanf("%d", &count);

    for (int i = 0; i < count; i++) {
        int x;
        printf("Enter number %d: ", i + 1);
        scanf("%d", &x);
        sum += x;
    }

    printf("Sum = %d, average = %.2f\n", sum, (float)sum / count);
    return 0;
}
