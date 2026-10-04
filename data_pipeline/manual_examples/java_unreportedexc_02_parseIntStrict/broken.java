import java.text.ParseException;

public class Main {
    public static void parseIntStrict(String text) {
        int n = Integer.parseInt(text);
        if (n < 0) throw new ParseException("negative", 0);
    }

    public static void main(String[] args) {
    }
}
