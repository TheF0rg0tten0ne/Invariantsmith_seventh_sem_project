public class Main {
    public static String classify(int n) {
        if (n > 0) {
            return "positive";
        } else if (n < 0) {
            return "negative";
        }
        return "zero";
    }

    public static void main(String[] args) {
        System.out.println(classify(-7));
    }
}
