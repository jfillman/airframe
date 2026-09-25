package io.skyport.flight;

import java.time.Instant;

/**
 * What is published to the broker when a flight changes: the change ({@code type}, {@code detail})
 * and the flight's state after it, so a consumer never has to call back to find out what is true now.
 */
public record FlightMessage(String flight, String type, String detail, String gate, int delayMinutes,
        Instant occurredAt) {

    /** {@code flight.AC123.gate_changed}: consumers bind on {@code flight.#} or {@code flight.AC123.*}. */
    public String routingKey() {
        return "flight." + flight + "." + type.toLowerCase();
    }
}
