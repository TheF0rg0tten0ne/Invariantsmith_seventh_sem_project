public class Main {
    public static int classify(int n) {
        if (n > 0) {
            return 1;
        } else if (n < 0) {
            return -1;
        }
        return 0;
    }

    public static void main(String[] args) {
        System.out.println(classify(5));
    }
}
