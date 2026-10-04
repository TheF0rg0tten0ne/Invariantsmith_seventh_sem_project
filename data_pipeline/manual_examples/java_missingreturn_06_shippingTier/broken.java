public class Main {
    public static int shippingTier(int weight) {
        if (weight > 50) {
            return 3;
        } else if (weight > 20) {
            return 2;
        }
    }

    public static void main(String[] args) {
        System.out.println(shippingTier(5));
    }
}
