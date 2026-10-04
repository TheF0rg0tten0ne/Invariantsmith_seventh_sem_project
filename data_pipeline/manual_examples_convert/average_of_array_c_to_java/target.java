public class Main {
    public static int average(int[] nums) {
        int total = 0;
        for (int n : nums) {
            total += n;
        }
        return total / nums.length;
    }

    public static void main(String[] args) {
        int[] nums = {10, 20, 30, 40};
        System.out.println(average(nums));
    }
}
