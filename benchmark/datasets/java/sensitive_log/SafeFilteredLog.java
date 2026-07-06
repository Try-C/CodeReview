package demo;

import java.util.logging.Logger;

/** Order processor that masks PII before logging. */
public class SafeFilteredLog {

    private static final Logger LOG = Logger.getLogger(SafeFilteredLog.class.getName());

    public void processOrder(String creditCard, String cvv, String ssn) {
        String maskedCard = "****-****-****-"
            + creditCard.substring(creditCard.length() - 4);
        LOG.info("Processing order — card: " + maskedCard);
    }
}
