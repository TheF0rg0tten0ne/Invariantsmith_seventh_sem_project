public class Main {
    static int classify(int score)
        if (score >= 90) {
            return 1;
        } else if (score >= 60) {
            return 2;
        } else {
            return 3;
        }
    }

    public static void main(String[] args) {
        System.out.println("Class: " + classify(75));
    }
}
