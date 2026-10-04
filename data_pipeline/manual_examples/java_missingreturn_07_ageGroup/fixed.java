public class Main {
    public static int ageGroup(int age) {
        if (age < 13) {
            return 0;
        } else if (age < 20) {
            return 1;
        }
        return 2;
    }

    public static void main(String[] args) {
        System.out.println(ageGroup(5));
    }
}
