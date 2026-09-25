package io.skyport.flight;

import java.util.List;
import java.util.Optional;

/** Persistence for flights and their change log. The Postgres implementation is {@link FlightRepository}. */
public interface FlightStore {

    List<Flight> all();

    Optional<Flight> find(String flightNumber);

    void setGate(String flightNumber, String gate);

    void setDelay(String flightNumber, int minutes);

    void addEvent(String flightNumber, String type, String detail);

    /** Most recent first. */
    List<FlightEvent> events(String flightNumber, int limit);
}
