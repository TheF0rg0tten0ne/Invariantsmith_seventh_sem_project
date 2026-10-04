import java.net.URL;
import java.io.IOException;

public class Main {
    public static void openUrlStream(String spec) throws IOException {
        URL url = new URL(spec);
        url.openStream();
    }

    public static void main(String[] args) {
    }
}
