package io.skyport.flight;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/** Used when events are off (the default), so the service runs with no broker at all. */
@Component
@ConditionalOnProperty(name = "events.enabled", havingValue = "false", matchIfMissing = true)
public class NoopFlightEventPublisher implements FlightEventPublisher {

    @Override
    public void publish(FlightMessage message) {
    }
}
