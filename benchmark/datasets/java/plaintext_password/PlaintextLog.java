package demo;

import java.util.logging.Logger;

/** Login handler that logs passwords in plaintext — CWE-256. */
public class PlaintextLog {

    private static final Logger LOG = Logger.getLogger(PlaintextLog.class.getName());

    public boolean authenticate(String username, String password) {
        // Vulnerable: password written to log in plaintext
        LOG.info("Authenticating user: " + username + " with password: " + password);
        return password != null && password.length() >= 8;
    }
}
