package demo;

/** Service that uses a hardcoded API key — CWE-798. */
public class HardcodedKey {

    private static final String API_KEY = "sk-proj-abc123def456ghi789jkl";

    public String callExternalService(String payload) {
        return "Called with key: " + API_KEY + ", payload: " + payload;
    }
}
