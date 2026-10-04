public class Main {
    public static int stockStatus(int qty) {
        if (qty == 0) {
            return 0;
        } else if (qty < 10) {
            return 1;
        }
        return 2;
    }

    public static void main(String[] args) {
        System.out.println(stockStatus(5));
    }
}
