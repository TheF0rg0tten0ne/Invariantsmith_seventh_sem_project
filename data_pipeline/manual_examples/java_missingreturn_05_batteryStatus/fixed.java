public class Main {
    public static int batteryStatus(int percent) {
        if (percent < 10) {
            return 0;
        } else if (percent < 50) {
            return 1;
        }
        return 2;
    }

    public static void main(String[] args) {
        System.out.println(batteryStatus(5));
    }
}
