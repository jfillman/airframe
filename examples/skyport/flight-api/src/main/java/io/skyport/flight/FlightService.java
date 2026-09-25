package io.skyport.flight;

import java.time.Instant;
import java.util.List;
import java.util.regex.Pattern;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
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
    private final FlightEventPublisher publisher;

    @Autowired
    public FlightService(FlightStore store, FlightEventPublisher publisher) {
        this.store = store;
        this.publisher = publisher;
    }

    public FlightService(FlightStore store) {
        this(store, message -> {
        });
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
        Flight after = get(f.flightNumber());
        publishAfterCommit(after, "GATE_CHANGED", f.gate() + " -> " + g);
        return after;
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
        String type = minutes == 0 ? "DELAY_CLEARED" : "DELAYED";
        String detail = f.delayMinutes() + " -> " + minutes + " min";
        store.addEvent(f.flightNumber(), type, detail);
        Flight after = get(f.flightNumber());
        publishAfterCommit(after, type, detail);
        return after;
    }

    /**
     * Only once the change is committed: a rolled-back change must not be announced. Outside a
     * transaction (unit tests) it publishes at once.
     */
    private void publishAfterCommit(Flight f, String type, String detail) {
        FlightMessage message = new FlightMessage(f.flightNumber(), type, detail, f.gate(), f.delayMinutes(),
                Instant.now());
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    publisher.publish(message);
                }
            });
        } else {
            publisher.publish(message);
        }
    }

    private static String normalise(String flightNumber) {
        String n = flightNumber == null ? "" : flightNumber.trim().toUpperCase();
        if (!FLIGHT.matcher(n).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "flight number looks like AC123");
        }
        return n;
    }
}
