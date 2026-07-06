package demo;

import java.sql.Connection;

/** Repository that performs writes without transaction boundaries — CWE-778. */
public class MissingTransaction {

    private Connection conn;

    public void transferFunds(int fromId, int toId, double amount) throws Exception {
        // Vulnerable: two writes without a transaction boundary
        conn.createStatement().executeUpdate(
            "UPDATE accounts SET balance = balance - " + amount + " WHERE id = " + fromId);
        conn.createStatement().executeUpdate(
            "UPDATE accounts SET balance = balance + " + amount + " WHERE id = " + toId);
    }
}
