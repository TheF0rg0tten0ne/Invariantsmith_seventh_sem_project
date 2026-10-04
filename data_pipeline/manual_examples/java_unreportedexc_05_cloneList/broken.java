public class Main {
    public static void cloneList(java.util.ArrayList<Integer> list) {
        java.util.ArrayList<Integer> copy = (java.util.ArrayList<Integer>) list.clone();
        if (copy.isEmpty()) throw new CloneNotSupportedException();
    }

    public static void main(String[] args) {
    }
}
