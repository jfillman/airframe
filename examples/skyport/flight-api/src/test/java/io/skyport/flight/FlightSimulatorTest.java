package io.skyport.flight;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Random;
import org.junit.jupiter.api.Test;

class FlightSimulatorTest {

    @Test
    void everyTickChangesSomethingAndRecordsIt() {
        FakeStore store = new FakeStore();
        FlightSimulator sim = new FlightSimulator(new FlightService(store), new Random(42));

        for (int i = 0; i < 50; i++) {
            sim.tick();
        }

        // A tick that picked a flight whose gate/delay would not change records nothing, but
        // with 50 ticks over two flights the log must have real entries.
        assertThat(store.events).isNotEmpty();
        assertThat(store.events).allSatisfy(e -> assertThat(e.type()).isIn("GATE_CHANGED", "DELAYED", "DELAY_CLEARED"));
    }

    @Test
    void gatesAlwaysComeFromTheKnownList() {
        FakeStore store = new FakeStore();
        FlightSimulator sim = new FlightSimulator(new FlightService(store), new Random(7));

        for (int i = 0; i < 100; i++) {
            sim.tick();
        }

        assertThat(store.flights.values()).allSatisfy(f -> assertThat(FlightSimulator.GATES).contains(f.gate()));
    }

    @Test
    void delaysNeverExceedTheRecoveryThreshold() {
        FakeStore store = new FakeStore();
        FlightSimulator sim = new FlightSimulator(new FlightService(store), new Random(3));

        for (int i = 0; i < 400; i++) {
            sim.tick();
            assertThat(store.flights.values()).allSatisfy(f -> assertThat(f.delayMinutes()).isLessThanOrEqualTo(75));
        }
    }
}
