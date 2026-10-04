import java.io.FileReader;
import java.io.IOException;

public class Main {
    public static void readFirstByte(String path) throws IOException {
        FileReader reader = new FileReader(path);
        try {
            reader.read();
        } finally {
            reader.close();
        }
    }

    public static void main(String[] args) {
    }
}
