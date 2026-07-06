package demo;

/** Controller endpoint without authentication — CWE-862. */
public class UnprotectedEndpoint {

    // Vulnerable: no authentication check before sensitive operation
    public String deleteUser(int userId) {
        return "User " + userId + " deleted";
    }
}
