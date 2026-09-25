package io.skyport.flight;

import java.sql.Time;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class FlightRepository implements FlightStore {

    private static final String COLUMNS =
            "flight_number, origin, destination, gate, scheduled_departure, delay_minutes, capacity, boarding_group";

    private final JdbcClient db;

    public FlightRepository(JdbcClient db) {
        this.db = db;
    }

    @Override
    public List<Flight> all() {
        return db.sql("SELECT " + COLUMNS + " FROM flights ORDER BY scheduled_departure, flight_number")
                .query((rs, n) -> map(rs.getString(1), rs.getString(2), rs.getString(3), rs.getString(4),
                        rs.getTime(5), rs.getInt(6), rs.getInt(7), rs.getInt(8)))
                .list();
    }

    @Override
    public Optional<Flight> find(String flightNumber) {
        return db.sql("SELECT " + COLUMNS + " FROM flights WHERE flight_number = :n")
                .param("n", flightNumber)
                .query((rs, n) -> map(rs.getString(1), rs.getString(2), rs.getString(3), rs.getString(4),
                        rs.getTime(5), rs.getInt(6), rs.getInt(7), rs.getInt(8)))
                .optional();
    }

    @Override
    public void setGate(String flightNumber, String gate) {
        db.sql("UPDATE flights SET gate = :g, updated_at = now() WHERE flight_number = :n")
                .param("g", gate)
                .param("n", flightNumber)
                .update();
    }

    @Override
    public void setDelay(String flightNumber, int minutes) {
        db.sql("UPDATE flights SET delay_minutes = :m, updated_at = now() WHERE flight_number = :n")
                .param("m", minutes)
                .param("n", flightNumber)
                .update();
    }

    @Override
    public void addEvent(String flightNumber, String type, String detail) {
        db.sql("INSERT INTO flight_events (flight_number, event_type, detail) VALUES (:n, :t, :d)")
                .param("n", flightNumber)
                .param("t", type)
                .param("d", detail)
                .update();
    }

    @Override
    public List<FlightEvent> events(String flightNumber, int limit) {
        return db.sql("SELECT id, flight_number, event_type, detail, occurred_at FROM flight_events "
                        + "WHERE flight_number = :n ORDER BY id DESC LIMIT :l")
                .param("n", flightNumber)
                .param("l", limit)
                .query((rs, n) -> new FlightEvent(rs.getLong(1), rs.getString(2), rs.getString(3),
                        rs.getString(4), rs.getTimestamp(5).toInstant()))
                .list();
    }

    private static Flight map(String number, String origin, String destination, String gate, Time departs,
                              int delay, int capacity, int group) {
        return new Flight(number, origin.trim(), destination.trim(), gate, departs.toLocalTime(), delay, capacity, group);
    }
}
