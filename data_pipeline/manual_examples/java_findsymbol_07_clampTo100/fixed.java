public class Main {
    public static int clampTo100(int x) {
        return x > 100 ? 100 : x;
    }

    public static void main(String[] args) {
        System.out.println(clampTo100(5));
    }
}
