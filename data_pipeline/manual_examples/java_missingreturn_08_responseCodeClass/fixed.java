public class Main {
    public static int responseCodeClass(int code) {
        if (code < 300) {
            return 0;
        } else if (code < 500) {
            return 1;
        }
        return 2;
    }

    public static void main(String[] args) {
        System.out.println(responseCodeClass(5));
    }
}
