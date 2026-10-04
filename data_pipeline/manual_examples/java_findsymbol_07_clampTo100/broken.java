public class Main {
    public static int clampTo100(int x) {
        return value > 100 ? 100 : value;
    }

    public static void main(String[] args) {
        System.out.println(clampTo100(5));
    }
}
