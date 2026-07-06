package demo;

import java.util.logging.Logger;

/** Order processor that logs PII — CWE-532. */
public class SensitiveLog {

    private static final Logger LOG = Logger.getLogger(SensitiveLog.class.getName());

    public void processOrder(String creditCard, String cvv, String ssn) {
        // Vulnerable: sensitive personal data written to log
        LOG.info("Processing order — card: " + creditCard
            + ", CVV: " + cvv + ", SSN: " + ssn);
    }
}
