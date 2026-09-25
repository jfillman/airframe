package io.skyport.flight;

import java.time.Instant;

/** One recorded change to a flight. */
public record FlightEvent(long id, String flight, String type, String detail, Instant occurredAt) {
}
