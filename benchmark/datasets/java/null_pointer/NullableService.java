package demo;

/** Service with potential null pointer dereference — CWE-476. */
public class NullableService {

    public String formatName(String firstName, String lastName) {
        // Vulnerable: lastName may be null, causing NPE
        return firstName + " " + lastName.toUpperCase();
    }
}
