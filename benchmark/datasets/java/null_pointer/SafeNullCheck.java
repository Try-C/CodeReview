package demo;

/** Safe null handling with explicit null check. */
public class SafeNullCheck {

    public String formatName(String firstName, String lastName) {
        if (lastName == null) {
            return firstName;
        }
        return firstName + " " + lastName.toUpperCase();
    }
}
