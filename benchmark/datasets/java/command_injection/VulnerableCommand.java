package demo;

import java.io.IOException;

/** Service that executes a shell command with user input — CWE-78. */
public class VulnerableCommand {

    public String ping(String host) throws IOException {
        // Vulnerable: user input passed directly to shell
        String cmd = "ping -c 1 " + host;
        Runtime.getRuntime().exec(cmd);
        return "Ping sent to " + host;
    }
}
