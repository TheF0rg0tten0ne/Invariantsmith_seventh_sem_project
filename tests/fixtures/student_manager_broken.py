#!/usr/bin/env python3

MAX_STUDENTS = 100
NAME_LEN = 50

# Structure to hold student data
Student = {
    'id': int,
    'name': str,
    'age': int,
    'gpa': float
}

# Global array and count
students = [Student() for _ in range(MAX_STUDENTS)]
student_count = 0

# Function prototypes
def add_student():
    if student_count >= MAX_STUDENTS:
        print('Database full!
')
        return
    student = Student()
    print('Enter ID: ', end='')
    student['id'] = int(input())
    print('Enter Name: ', end='')
    student['name'] = input().strip()
    print('Enter Age: ', end='')
    student['age'] = int(input())
    print('Enter GPA: ', end='')
    student['gpa'] = float(input())
    students[student_count] = student
    print('Student added successfully!
')

def list_students():
    if student_count == 0:
        print('No students found.
')
        return
    print('--- Student List ---
')
    for student in students:
        print(f'ID: {student["id"]} | Name: {student["name"]} | Age: {student["age"]} | GPA: {student["gpa"]:.2f}
')

def search_student():
    id = int(input('Enter ID to search: '))
    index = find_student_by_id(id)
    if index == -1:
        print('Student not found.
')
    else:
        print(f'Student found:
{student_to_str(students[index])}
')

def update_student():
    id = int(input('Enter ID to update: '))
    index = find_student_by_id(id)
    if index == -1:
        print('Student not found.
')
        return
    print('Updating student {id}...
')
    print('Enter new name: ', end='')
    student['name'] = input().strip()
    print('Enter new age: ', end='')
    student['age'] = int(input())
    print('Enter new GPA: ', end='')
    student['gpa'] = float(input())
    print('Student updated successfully!
')

# Delete student
def delete_student():
    id = int(input('Enter ID to delete: '))
    index = find_student_by_id(id)
    if index == -1:
        print('Student not found.
')
        return
    for i in range(index, student_count - 1):
        students[i] = students[i + 1]
    student_count -= 1
    print('Student deleted successfully!
')

# Find student by ID
def find_student_by_id(id):
    for i in range(student_count):
        if students[i]['id'] == id:
            return i
    return -1

# Convert a Student dict to a string
def student_to_str(student):
    return f'ID: {student["id"]} | Name: {student["name"]} | Age: {student["age"]} | GPA: {student["gpa"]:.2f}

# Clear input buffer
def clear_input_buffer():
    input().strip()

# Main menu
def menu():
    print("===== Student Management System =====")
    print("1. Add Student")
    print("2. List Students")
    print("3. Search Student")
    print("4. Update Student")
    print("5. Delete Student")
    print("6. Exit")
    print("=====================================")

# Report function
def report():
    print("--- Report ---")
    list_students()
    average_gpa()
    sort_by_gpa()
    list_students()
    print("--- End Report ---")

# Main function
if __name__ == '__main__':
    choice = 0
    while choice != 6:
        menu()
        print("Enter choice: ", end='')
        choice = int(input())
        clear_input_buffer()

        if choice == 1:
            add_student()
        elif choice == 2:
            list_students()
        elif choice == 3:
            search_student()
        elif choice == 4:
            update_student()
        elif choice == 5:
            delete_student()
        elif choice == 6:
            print("Exiting program...
")
            break
        else:
            print("Invalid choice. Try again.
")

# Helper functions
def average_gpa():
    if student_count == 0:
        print('No students to calculate average.
')
        return
    total_gpa = sum(student['gpa'] for student in students)
    print(f'Average GPA: {total_gpa / student_count:.2f}
')

def sort_by_gpa():
    for i in range(student_count - 1):
        for j in range(i + 1, student_count):
            if students[i]['gpa'] < students[j]['gpa']:
                students[i], students[j] = students[j], students[i]
    print('Students sorted by GPA.
')

# Extra filler: simulate reports
report()
