public class Main {
    public static int tempAlertLevel(int temp) {
        if (temp > 100) {
            return 2;
        } else if (temp > 80) {
            return 1;
        }
    }

    public static void main(String[] args) {
        System.out.println(tempAlertLevel(5));
    }
}
