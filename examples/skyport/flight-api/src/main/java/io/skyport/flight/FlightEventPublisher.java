package io.skyport.flight;

/** Where flight changes go once they are committed. */
public interface FlightEventPublisher {

    /** Must not throw: a broker problem never fails the change that was already saved. */
    void publish(FlightMessage message);
}
