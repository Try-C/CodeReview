package demo;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;

/** User data access — demonstrates SQL injection via string concatenation. */
public class VulnerableService {

    public void findUser(String username) throws Exception {
        Connection conn = DriverManager.getConnection("jdbc:h2:mem:test");
        Statement stmt = conn.createStatement();
        // Vulnerable: user input concatenated into SQL
        String sql = "SELECT * FROM users WHERE username = '" + username + "'";
        stmt.executeQuery(sql);
    }
}
