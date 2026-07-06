package demo;

/** Safe configuration: API key loaded from environment variable. */
public class SafeConfigKey {

    public String callExternalService(String payload) {
        String apiKey = System.getenv("EXTERNAL_API_KEY");
        if (apiKey == null) {
            throw new IllegalStateException("EXTERNAL_API_KEY not configured");
        }
        return "Called with key: ***, payload: " + payload;
    }
}
