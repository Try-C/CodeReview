package demo;

import java.sql.Connection;

/** Repository using explicit transaction boundaries. */
public class SafeTransaction {

    private Connection conn;

    public void transferFunds(int fromId, int toId, double amount) throws Exception {
        conn.setAutoCommit(false);
        try {
            conn.createStatement().executeUpdate(
                "UPDATE accounts SET balance = balance - " + amount + " WHERE id = " + fromId);
            conn.createStatement().executeUpdate(
                "UPDATE accounts SET balance = balance + " + amount + " WHERE id = " + toId);
            conn.commit();
        } catch (Exception e) {
            conn.rollback();
            throw e;
        }
    }
}
