package demo;

import java.io.IOException;
import java.util.List;

/** Service that safely executes a command using argument lists. */
public class SafeCommand {

    public String ping(String host) throws IOException {
        // Safe: argument list prevents shell injection
        ProcessBuilder pb = new ProcessBuilder(List.of("ping", "-c", "1", host));
        pb.start();
        return "Ping sent to " + host;
    }
}
