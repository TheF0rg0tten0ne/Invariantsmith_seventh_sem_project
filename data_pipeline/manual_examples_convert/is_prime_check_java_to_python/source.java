public class Main {
    public static boolean isPrime(int n) {
        if (n < 2) {
            return false;
        }
        for (int d = 2; d < n; d++) {
            if (n % d == 0) {
                return false;
            }
        }
        return true;
    }

    public static void main(String[] args) {
        System.out.println(isPrime(17));
    }
}
