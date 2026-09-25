package io.skyport.flight;

import java.time.format.DateTimeFormatter;

/**
 * The JSON shape of a flight. {@code flight}, {@code gate}, {@code destination}, {@code departs},
 * {@code capacity} and {@code group} are exactly what boarding-api's lookup already returns,
 * so the gate board can use this service in place of its built-in stand-in unchanged.
 */
public record FlightView(
        String flight,
        String origin,
        String destination,
        String gate,
        String status,
        String departs,
        String estimatedDeparture,
        int delayMinutes,
        int capacity,
        int group) {

    private static final DateTimeFormatter HH_MM = DateTimeFormatter.ofPattern("HH:mm");

    public static FlightView of(Flight f) {
        return new FlightView(
                f.flightNumber(),
                f.origin(),
                f.destination(),
                f.gate(),
                f.delayMinutes() > 0 ? "DELAYED" : "ON_TIME",
                f.scheduledDeparture().format(HH_MM),
                f.estimatedDeparture().format(HH_MM),
                f.delayMinutes(),
                f.capacity(),
                f.boardingGroup());
    }
}
