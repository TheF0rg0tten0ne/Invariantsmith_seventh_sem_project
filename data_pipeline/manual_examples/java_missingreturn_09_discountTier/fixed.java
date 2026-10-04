public class Main {
    public static int discountTier(int total) {
        if (total > 100) {
            return 20;
        } else if (total > 50) {
            return 10;
        }
        return 0;
    }

    public static void main(String[] args) {
        System.out.println(discountTier(5));
    }
}
