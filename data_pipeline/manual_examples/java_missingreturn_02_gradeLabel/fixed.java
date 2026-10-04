public class Main {
    public static int gradeLabel(int score) {
        if (score >= 90) {
            return 1;
        } else if (score >= 60) {
            return 2;
        }
        return 3;
    }

    public static void main(String[] args) {
        System.out.println(gradeLabel(5));
    }
}
