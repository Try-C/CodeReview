package demo;

/** Controller endpoint with role-based access control. */
public class SafeAuthenticated {

    private boolean currentUserIsAdmin() {
        return false;
    }

    public String deleteUser(int userId) {
        if (!currentUserIsAdmin()) {
            throw new SecurityException("Admin role required");
        }
        return "User " + userId + " deleted";
    }
}
