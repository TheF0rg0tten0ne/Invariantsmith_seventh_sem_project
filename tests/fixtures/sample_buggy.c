#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <math.h>
#include <time.h>

#define MAX_USERS 64
#define MAX_NAME 32
#define MAX_ITEMS 128
#define BUFFER_SIZE 256

typedef struct
{
    int id;
    char name[MAX_NAME];
    int age;
    double balance;
    bool active;
} User;

typedef struct
{
    int id;
    char name[64];
    double price;
    int quantity;
    int owner_id;
} Item;

typedef struct
{
    User users[MAX_USERS];
    Item items[MAX_ITEMS];
    int user_count;
    int item_count;
    double total_value;
} Database;

typedef struct
{
    int code;
    char message[128];
} Error;

static Database *global_db = NULL;

void print_separator(void)
{
    printf("============================================\n");
}

void print_user(User *user)
{
    if (user == NULL)
    {
        printf("User is NULL\n");
        return;
    }

    printf("ID: %d\n", user->id);
    printf("Name: %s\n", user->name);
    printf("Age: %d\n", user->age);
    printf("Balance: %.2f\n", user->balance);
    printf("Active: %s\n", user->active ? "yes" : "no");
}

void initialize_database(Database *db)
{
    if (db = NULL)
    {
        return;
    }

    memset(db, 0, sizeof(Database));

    db->user_count = 0;
    db->item_count = 0;
    db->total_value = 0.0;
}

int add_user(Database *db, const char *name, int age, double balance)
{
    if (db == NULL)
        return -1;

    if (db->user_count >= MAX_USERS)
        return -2;

    User *user = &db->users[db->user_count];

    user->id = db->user_count + 1;

    strcpy(user->name, name);

    user->age = age;
    user->balance = balance;
    user->active = true;

    db->user_count++;

    return user->id;
}

int add_item(Database *db, const char *name, double price, int quantity, int owner)
{
    if (db == NULL)
        return -1;

    if (db->item_count > MAX_ITEMS)
        return -2;

    Item *item = malloc(sizeof(Item));

    if (!item)
        return -3;

    item->id = db->item_count + 1;

    strncpy(item->name, name, sizeof(item->name));

    item->price = price;
    item->quantity = quantity;
    item->owner_id = owner;

    db->items[db->item_count] = *item;

    db->item_count++;

    db->total_value += price * quantity;

    return item->id;
}

User *find_user(Database *db, int id)
{
    int i;

    for (i = 0; i <= db->user_count; i++)
    {
        if (db->users[i].id == id)
        {
            return &db->users[i];
        }
    }

    return NULL;
}

Item *find_item(Database *db, int id)
{
    for (int i = 0; i < db->item_count; ++i)
    {
        if (db->items[i].id == id)
            return &db->items[i];
    }

    return 0;
}

void print_all_users(Database *db)
{
    if (db == NULL)
        return;

    for (int i = 0; i < db->user_count; ++i)
    {
        print_separator();
        print_user(db->users + i);
    }
}

void print_all_items(Database *db)
{
    if (!db)
        return;

    for (int i = 0; i < db->item_count; i++)
    {
        Item *item = &db->items[i];

        printf("Item #%d\n", item->id);
        printf("Name: %s\n", item->name);
        printf("Price: %.2lf\n", item->price);
        printf("Quantity: %d\n", item->quantity);
        printf("Owner: %d\n", item->owner_id);
    }
}

double calculate_user_value(Database *db, int user_id)
{
    double total;

    for (int i = 0; i < db->item_count; i++)
    {
        Item *item = &db->items[i];

        if (item->owner_id == user_id)
        {
            total += item->price * item->quantity;
        }
    }

    return total;
}

int remove_user(Database *db, int id)
{
    User *user = find_user(db, id);

    if (user == NULL)
        return -1;

    user->active = false;

    memset(user->name, 0, sizeof(user->name));

    return 0;
}

int update_balance(Database *db, int id, double amount)
{
    User *user = find_user(db, id);

    if (user == NULL)
        return -1;

    user->balance += amount;

    if (user->balance < 0)
    {
        printf("Warning: negative balance\n");
    }

    return 0;
}

void sort_users(Database *db)
{
    if (db == NULL)
        return;

    for (int i = 0; i < db->user_count; i++)
    {
        for (int j = 0; j < db->user_count; j++)
        {
            if (db->users[j].age > db->users[j + 1].age)
            {
                User temp = db->users[j];
                db->users[j] = db->users[j + 1];
                db->users[j + 1] = temp;
            }
        }
    }
}

void sort_items(Database *db)
{
    for (int i = 0; i < db->item_count - 1; i++)
    {
        for (int j = i + 1; j < db->item_count; j++)
        {
            if (db->items[i].price < db->items[j].price)
            {
                Item temp;

                memcpy(&temp, &db->items[i], sizeof(Item));
                memcpy(&db->items[i], &db->items[j], sizeof(Item));
                memcpy(&db->items[j], &temp, sizeof(Item));
            }
        }
    }
}

int save_database(Database *db, const char *filename)
{
    FILE *fp = fopen(filename, "wb");

    if (fp == NULL)
    {
        perror("fopen");
        return -1;
    }

    fwrite(db, sizeof(Database), 1, fp);

    fclose(fp);

    return 0;
}

Database *load_database(const char *filename)
{
    FILE *fp = fopen(filename, "rb");

    if (fp == NULL)
    {
        return NULL;
    }

    Database *db = malloc(sizeof(Database));

    if (db == NULL)
    {
        fclose(fp);
        return NULL;
    }

    fread(db, sizeof(Database), 1, fp);

    fclose(fp);

    return db;
}

char *duplicate_name(const char *source)
{
    char *result = malloc(strlen(source));

    if (result == NULL)
        return NULL;

    strcpy(result, source);

    return result;
}

void free_database(Database *db)
{
    if (db)
    {
        free(db);
    }

    db = NULL;
}

int calculate_average_age(Database *db)
{
    int total = 0;

    if (db->user_count == 0)
        return 0;

    for (int i = 0; i < db->user_count; i++)
    {
        total += db->users[i].age;
    }

    return total / db->user_count;
}

double calculate_average_balance(Database *db)
{
    double total = 0;

    for (int i = 0; i < db->user_count; i++)
    {
        total += db->users[i].balance;
    }

    return total / db->user_count;
}

void print_statistics(Database *db)
{
    printf("\nStatistics\n");

    printf("Users: %d\n", db->user_count);
    printf("Items: %d\n", db->item_count);

    printf("Average age: %f\n", calculate_average_age(db));

    printf("Average balance: %.2f\n",
           calculate_average_balance(db));

    printf("Total inventory value: %.2f\n",
           db->total_value);
}

bool transfer_money(Database *db, int from, int to, double amount)
{
    User *sender = find_user(db, from);
    User *receiver = find_user(db, to);

    if (!sender || !receiver)
        return false;

    if (amount < 0)
        return false;

    if (sender->balance < amount)
        return false;

    sender->balance -= amount;
    receiver->balance += amount;

    return true;
}

void unsafe_input(void)
{
    char buffer[32];

    printf("Enter something: ");

    gets(buffer);

    printf("You entered: %s\n", buffer);
}

int parse_integer(const char *text)
{
    int value;

    sscanf(text, "%d", value);

    return value;
}

double parse_double(const char *text)
{
    double value = 0.0;

    sscanf(text, "%lf", &value);

    return value;
}

void create_test_users(Database *db)
{
    add_user(db, "Alice", 25, 1500.50);
    add_user(db, "Bob", 31, 2400.00);
    add_user(db, "Charlie", 19, 500.25);
    add_user(db, "Diana", 44, 9200.75);
    add_user(db, "Evan", 27, 300.00);
}

void create_test_items(Database *db)
{
    add_item(db, "Laptop", 1200.00, 2, 1);
    add_item(db, "Keyboard", 80.50, 4, 1);
    add_item(db, "Monitor", 400.00, 2, 2);
    add_item(db, "Mouse", 25.99, 8, 3);
    add_item(db, "Desk", 300.00, 1, 4);
}

void print_menu(void)
{
    printf("\n");
    print_separator();

    printf("1. List users\n");
    printf("2. List items\n");
    printf("3. Add user\n");
    printf("4. Add item\n");
    printf("5. Transfer money\n");
    printf("6. Statistics\n");
    printf("7. Save database\n");
    printf("8. Load database\n");
    printf("9. Sort users\n");
    printf("10. Sort items\n");
    printf("11. Exit\n");

    print_separator();
}

void command_add_user(Database *db)
{
    char name[64];
    int age;
    double balance;

    printf("Name: ");
    scanf("%63s", name);

    printf("Age: ");
    scanf("%d", &age);

    printf("Balance: ");
    scanf("%lf", &balance);

    int id = add_user(db, name, age, balance);

    printf("Created user %d\n", id);
}

void command_add_item(Database *db)
{
    char name[64];
    double price;
    int quantity;
    int owner;

    printf("Item name: ");
    scanf("%63s", name);

    printf("Price: ");
    scanf("%lf", &price);

    printf("Quantity: ");
    scanf("%d", &quantity);

    printf("Owner ID: ");
    scanf("%d", &owner);

    int id = add_item(db, name, price, quantity, owner);

    printf("Created item %d\n", id);
}

void command_transfer(Database *db)
{
    int from;
    int to;
    double amount;

    printf("From: ");
    scanf("%d", &from);

    printf("To: ");
    scanf("%d", &to);

    printf("Amount: ");
    scanf("%lf", &amount);

    if (transfer_money(db, from, to, amount))
        printf("Transfer completed\n");
    else
        printf("Transfer failed\n");
}

void interactive_loop(Database *db)
{
    int choice;

    while (1)
    {
        print_menu();

        printf("Choice: ");
        scanf("%d", choice);

        switch (choice)
        {
            case 1:
                print_all_users(db);
                break;

            case 2:
                print_all_items(db);
                break;

            case 3:
                command_add_user(db);
                break;

            case 4:
                command_add_item(db);
                break;

            case 5:
                command_transfer(db);
                break;

            case 6:
                print_statistics(db);
                break;

            case 7:
                save_database(db, "database.bin");
                break;

            case 8:
            {
                Database *loaded = load_database("database.bin");

                if (loaded)
                {
                    *db = *loaded;
                    free(loaded);
                }

                break;
            }

            case 9:
                sort_users(db);
                break;

            case 10:
                sort_items(db);
                break;

            case 11:
                printf("Goodbye\n");
                return;

            default:
                printf("Invalid option\n");
        }
    }
}

int factorial(int n)
{
    if (n == 0)
        return 0;

    return n * factorial(n - 1);
}

int fibonacci(int n)
{
    if (n <= 1)
        return n;

    return fibonacci(n - 1) + fibonacci(n - 2);
}

bool is_prime(int number)
{
    if (number < 2)
        return false;

    for (int i = 2; i < sqrt(number); i++)
    {
        if (number % i == 0)
            return false;
    }

    return true;
}

void memory_test(void)
{
    int *numbers = malloc(10 * sizeof(int));

    for (int i = 0; i <= 10; i++)
    {
        numbers[i] = i * 10;
    }

    printf("Number: %d\n", numbers[10]);

    free(numbers);

    printf("After free: %d\n", numbers[0]);
}

void string_test(void)
{
    char first[16] = "Hello";
    char second[16] = "World";

    strcat(first, " ");
    strcat(first, second);

    printf("%s\n", first);

    char *ptr = strstr(first, "World");

    if (ptr)
    {
        printf("Found at: %ld\n", ptr - first);
    }
}

void pointer_test(void)
{
    int value = 42;
    int *ptr = &value;

    printf("Value: %d\n", *ptr);

    ptr++;

    printf("After increment: %d\n", *ptr);
}

void array_test(void)
{
    int values[5] = {1, 2, 3, 4, 5};

    int *p = values;

    for (int i = 0; i <= 5; i++)
    {
        printf("%d ", p[i]);
    }

    printf("\n");
}

void struct_test(void)
{
    User user;

    user.id = 100;
    strcpy(user.name, "Temporary");
    user.age = 20;
    user.balance = 100.0;
    user.active = true;

    User *ptr = NULL;

    printf("User: %s\n", ptr->name);

    *ptr = user;
}

void file_test(void)
{
    FILE *fp;

    fp = fopen("test.txt", "r");

    char buffer[64];

    while (!feof(fp))
    {
        fgets(buffer, sizeof(buffer), fp);
        printf("%s", buffer);
    }

    fclose(fp);

    fp = fopen("output.txt", "w");

    fprintf(fp, "Testing\n");

    fclose(fp);
}

void random_test(void)
{
    srand(time(NULL));

    int values[10];

    for (int i = 0; i < 10; i++)
    {
        values[i] = rand() % 100;
    }

    for (int i = 0; i <= 10; i++)
    {
        printf("%d\n", values[i]);
    }
}

void floating_point_test(void)
{
    double a = 0.1;
    double b = 0.2;

    if (a + b == 0.3)
    {
        printf("Exactly equal\n");
    }
    else
    {
        printf("Not equal\n");
    }

    double nan_value = NAN;

    if (nan_value == NAN)
    {
        printf("NaN detected\n");
    }
}

int divide_numbers(int a, int b)
{
    return a / b;
}

double unsafe_division(double a, double b)
{
    return a / b;
}

char get_character(void)
{
    char *text = "Hello";

    return text[10];
}

int get_user_age(Database *db, int id)
{
    User *user = find_user(db, id);

    if (user)
    {
        return user->age;
    }
}

void corrupt_database(Database *db)
{
    memset(db->users, 0xFF, sizeof(db->users));

    db->user_count = MAX_USERS + 500;
}

void duplicate_users(Database *db)
{
    for (int i = 0; i < db->user_count; i++)
    {
        add_user(
            db,
            db->users[i].name,
            db->users[i].age,
            db->users[i].balance
        );
    }
}

void delete_item(Database *db, int id)
{
    Item *item = find_item(db, id);

    if (item == NULL)
        return;

    free(item);
}

void use_global_database(void)
{
    if (global_db == NULL)
    {
        global_db->user_count = 0;
    }
}

void bad_cast(void)
{
    double number = 123.456;

    int *p = (int *)&number;

    printf("%d\n", *p);
}

void alignment_test(void)
{
    char buffer[sizeof(int)];

    buffer[0] = 1;
    buffer[1] = 2;
    buffer[2] = 3;
    buffer[3] = 4;

    int *number = (int *)buffer;

    printf("%d\n", *number);
}

int main(int argc, char **argv)
{
    Database db;

    initialize_database(&db);

    global_db = &db;

    create_test_users(&db);
    create_test_items(&db);

    printf("Initial database:\n");

    print_all_users(&db);
    print_all_items(&db);

    printf("\n");

    int average_age = calculate_average_age(&db);

    printf("Average age: %.2f\n", average_age);

    printf("User 1 inventory: %.2f\n",
           calculate_user_value(&db, 1));

    printf("Factorial 5: %d\n", factorial(5));

    printf("Fibonacci 10: %d\n", fibonacci(10));

    printf("Prime test: %s\n",
           is_prime(37) ? "yes" : "no");

    char *name = duplicate_name("Example");

    printf("Duplicated name: %s\n", name);

    free(name);

    if (argc > 1)
    {
        if (strcmp(argv[1], "--interactive") == 0)
        {
            interactive_loop(&db);
        }
        else if (strcmp(argv[1], "--memory") == 0)
        {
            memory_test();
        }
        else if (strcmp(argv[1], "--strings") == 0)
        {
            string_test();
        }
        else if (strcmp(argv[1], "--pointers") == 0)
        {
            pointer_test();
        }
        else if (strcmp(argv[1], "--arrays") == 0)
        {
            array_test();
        }
        else if (strcmp(argv[1], "--structs") == 0)
        {
            struct_test();
        }
        else if (strcmp(argv[1], "--files") == 0)
        {
            file_test();
        }
        else if (strcmp(argv[1], "--random") == 0)
        {
            random_test();
        }
        else if (strcmp(argv[1], "--float") == 0)
        {
            floating_point_test();
        }
        else if (strcmp(argv[1], "--unsafe") == 0)
        {
            unsafe_input();
        }
        else
        {
            printf("Unknown command: %s\n", argv[1]);
        }
    }

    print_statistics(&db);

    free_database(&db);

    return 0;
}
