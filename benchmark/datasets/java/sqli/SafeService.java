package demo;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;

/** Safe data access using PreparedStatement with parameter binding. */
public class SafeService {

    public void findUser(String username) throws Exception {
        Connection conn = DriverManager.getConnection("jdbc:h2:mem:test");
        String sql = "SELECT * FROM users WHERE username = ?";
        PreparedStatement ps = conn.prepareStatement(sql);
        ps.setString(1, username);
        ps.executeQuery();
    }
}
