import java.io.FileReader;
import java.io.IOException;

public class Main {
    public static void readFirstByte(String path) {
        FileReader reader = new FileReader(path);
        int b = reader.read();
        reader.close();
    }

    public static void main(String[] args) {
    }
}
