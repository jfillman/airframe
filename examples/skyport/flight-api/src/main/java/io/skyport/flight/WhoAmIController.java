package io.skyport.flight;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** Which version and pod answered: the same probe boarding-api exposes for the canary board. */
@RestController
public class WhoAmIController {

    private final String version;

    public WhoAmIController(@Value("${app.version}") String version) {
        this.version = version;
    }

    @GetMapping("/api/whoami")
    public Map<String, String> whoami() {
        return Map.of("service", "flight-api", "version", version, "pod", pod(), "database", "postgresql");
    }

    private static String pod() {
        String h = System.getenv("HOSTNAME");
        if (h != null && !h.isBlank()) {
            return h;
        }
        try {
            return InetAddress.getLocalHost().getHostName();
        } catch (UnknownHostException e) {
            return "unknown";
        }
    }
}
