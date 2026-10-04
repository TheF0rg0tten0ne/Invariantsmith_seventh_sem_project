public class Main {
    public static int priorityLevel(int severity) {
        if (severity > 8) {
            return 3;
        } else if (severity > 4) {
            return 2;
        }
        return 1;
    }

    public static void main(String[] args) {
        System.out.println(priorityLevel(5));
    }
}
