package io.skyport.flight;

import java.util.List;
import java.util.regex.Pattern;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

/**
 * Flight rules. Every change is written together with its {@link FlightEvent} in one
 * transaction, so the change log can never disagree with the flights table.
 */
@Service
public class FlightService {

    static final Pattern FLIGHT = Pattern.compile("^[A-Z]{2}\\d{1,4}$");
    static final Pattern GATE = Pattern.compile("^[A-D]\\d{1,2}$");
    static final int MAX_DELAY_MINUTES = 240;

    private final FlightStore store;

    public FlightService(FlightStore store) {
        this.store = store;
    }

    public List<Flight> all() {
        return store.all();
    }

    public Flight get(String flightNumber) {
        return store.find(normalise(flightNumber))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "no such flight: " + flightNumber));
    }

    public List<FlightEvent> events(String flightNumber, int limit) {
        Flight f = get(flightNumber);
        return store.events(f.flightNumber(), Math.max(1, Math.min(limit, 100)));
    }

    @Transactional
    public Flight changeGate(String flightNumber, String gate) {
        Flight f = get(flightNumber);
        String g = gate == null ? "" : gate.trim().toUpperCase();
        if (!GATE.matcher(g).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "gate looks like B7 (A-D, then 1-2 digits)");
        }
        if (g.equals(f.gate())) {
            return f;
        }
        store.setGate(f.flightNumber(), g);
        store.addEvent(f.flightNumber(), "GATE_CHANGED", f.gate() + " -> " + g);
        return get(f.flightNumber());
    }

    @Transactional
    public Flight delay(String flightNumber, int minutes) {
        Flight f = get(flightNumber);
        if (minutes < 0 || minutes > MAX_DELAY_MINUTES) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "delay must be between 0 and " + MAX_DELAY_MINUTES + " minutes");
        }
        if (minutes == f.delayMinutes()) {
            return f;
        }
        store.setDelay(f.flightNumber(), minutes);
        store.addEvent(f.flightNumber(), minutes == 0 ? "DELAY_CLEARED" : "DELAYED",
                f.delayMinutes() + " -> " + minutes + " min");
        return get(f.flightNumber());
    }

    private static String normalise(String flightNumber) {
        String n = flightNumber == null ? "" : flightNumber.trim().toUpperCase();
        if (!FLIGHT.matcher(n).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "flight number looks like AC123");
        }
        return n;
    }
}
