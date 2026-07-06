package demo;

import java.util.logging.Logger;

/** Login handler that masks sensitive data in logs. */
public class SafeMaskedLog {

    private static final Logger LOG = Logger.getLogger(SafeMaskedLog.class.getName());

    public boolean authenticate(String username, String password) {
        LOG.info("Authenticating user: " + username);
        return password != null && password.length() >= 8;
    }
}
