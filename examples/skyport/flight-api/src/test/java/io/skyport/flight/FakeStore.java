package io.skyport.flight;

import java.time.Instant;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/** In-memory {@link FlightStore} so the rules can be tested without a database. */
class FakeStore implements FlightStore {

    final Map<String, Flight> flights = new LinkedHashMap<>();
    final List<FlightEvent> events = new ArrayList<>();

    FakeStore() {
        add("AC123", "A1", 0);
        add("WS410", "B7", 30);
    }

    void add(String number, String gate, int delay) {
        flights.put(number, new Flight(number, "YVR", "YYZ", gate, LocalTime.of(9, 0), delay, 150, 2));
    }

    @Override
    public List<Flight> all() {
        return List.copyOf(flights.values());
    }

    @Override
    public Optional<Flight> find(String n) {
        return Optional.ofNullable(flights.get(n));
    }

    @Override
    public void setGate(String n, String gate) {
        Flight f = flights.get(n);
        flights.put(n, new Flight(n, f.origin(), f.destination(), gate, f.scheduledDeparture(), f.delayMinutes(),
                f.capacity(), f.boardingGroup()));
    }

    @Override
    public void setDelay(String n, int minutes) {
        Flight f = flights.get(n);
        flights.put(n, new Flight(n, f.origin(), f.destination(), f.gate(), f.scheduledDeparture(), minutes,
                f.capacity(), f.boardingGroup()));
    }

    @Override
    public void addEvent(String n, String type, String detail) {
        events.add(new FlightEvent(events.size() + 1L, n, type, detail, Instant.EPOCH));
    }

    @Override
    public List<FlightEvent> events(String n, int limit) {
        return events.stream().filter(e -> e.flight().equals(n)).limit(limit).toList();
    }
}
