package io.skyport.flight;

import java.util.List;
import java.util.Random;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Keeps the demo alive: on a timer, picks a flight and either moves it to another gate or
 * changes its delay. Goes through {@link FlightService}, so it is subject to the same rules and
 * writes the same events as an API caller would.
 */
@Component
@ConditionalOnProperty(name = "simulator.enabled", havingValue = "true")
public class FlightSimulator {

    private static final Logger log = LoggerFactory.getLogger(FlightSimulator.class);
    static final List<String> GATES = List.of("A1", "A4", "B2", "B7", "C3", "C9", "D5");

    private final FlightService flights;
    private final Random random;

    @Autowired
    public FlightSimulator(FlightService flights) {
        this(flights, new Random());
    }

    FlightSimulator(FlightService flights, Random random) {
        this.flights = flights;
        this.random = random;
    }

    @Scheduled(fixedDelayString = "${simulator.interval-ms}", initialDelayString = "${simulator.interval-ms}")
    public void tick() {
        List<Flight> all = flights.all();
        if (all.isEmpty()) {
            return;
        }
        Flight f = all.get(random.nextInt(all.size()));
        if (random.nextBoolean()) {
            String gate;
            do {
                gate = GATES.get(random.nextInt(GATES.size()));
            } while (gate.equals(f.gate()));
            flights.changeGate(f.flightNumber(), gate);
            log.info("simulator: {} moved from gate {} to {}", f.flightNumber(), f.gate(), gate);
        } else {
            // Grow a delay in 15-minute steps; once it reaches an hour the flight recovers.
            int minutes = f.delayMinutes() >= 60 ? 0 : f.delayMinutes() + 15;
            flights.delay(f.flightNumber(), minutes);
            log.info("simulator: {} delay {} -> {} min", f.flightNumber(), f.delayMinutes(), minutes);
        }
    }
}
