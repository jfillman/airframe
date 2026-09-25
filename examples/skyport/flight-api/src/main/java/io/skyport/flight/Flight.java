package io.skyport.flight;

import java.time.LocalTime;

/** A departing flight as stored. {@link FlightView} is what the API returns. */
public record Flight(
        String flightNumber,
        String origin,
        String destination,
        String gate,
        LocalTime scheduledDeparture,
        int delayMinutes,
        int capacity,
        int boardingGroup) {

    public LocalTime estimatedDeparture() {
        return scheduledDeparture.plusMinutes(delayMinutes);
    }
}
