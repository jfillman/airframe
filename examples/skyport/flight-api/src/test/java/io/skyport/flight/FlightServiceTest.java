package io.skyport.flight;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

class FlightServiceTest {

    private final FakeStore store = new FakeStore();
    private final FlightService service = new FlightService(store);

    @Test
    void gateChangeUpdatesTheFlightAndRecordsAnEvent() {
        Flight f = service.changeGate("ac123", "b2");

        assertThat(f.gate()).isEqualTo("B2");
        assertThat(store.events).singleElement().satisfies(e -> {
            assertThat(e.flight()).isEqualTo("AC123");
            assertThat(e.type()).isEqualTo("GATE_CHANGED");
            assertThat(e.detail()).isEqualTo("A1 -> B2");
        });
    }

    @Test
    void movingToTheSameGateIsANoOpWithNoEvent() {
        service.changeGate("AC123", "A1");

        assertThat(store.events).isEmpty();
    }

    @Test
    void badGateIsRejectedAndNothingIsWritten() {
        assertThatThrownBy(() -> service.changeGate("AC123", "Z99"))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        e -> assertThat(e.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST));
        assertThat(store.flights.get("AC123").gate()).isEqualTo("A1");
        assertThat(store.events).isEmpty();
    }

    @Test
    void unknownFlightIsNotFound() {
        assertThatThrownBy(() -> service.get("AC999"))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        e -> assertThat(e.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND));
    }

    @Test
    void malformedFlightNumberIsABadRequestNotANotFound() {
        assertThatThrownBy(() -> service.get("not a flight"))
                .isInstanceOfSatisfying(ResponseStatusException.class,
                        e -> assertThat(e.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST));
    }

    @Test
    void delayMovesTheEstimatedDepartureAndRecordsIt() {
        Flight f = service.delay("AC123", 45);

        assertThat(f.estimatedDeparture()).hasToString("09:45");
        assertThat(FlightView.of(f).status()).isEqualTo("DELAYED");
        assertThat(store.events).singleElement().satisfies(e -> {
            assertThat(e.type()).isEqualTo("DELAYED");
            assertThat(e.detail()).isEqualTo("0 -> 45 min");
        });
    }

    @Test
    void clearingADelayIsRecordedAsCleared() {
        service.delay("WS410", 0);

        assertThat(store.events).singleElement().satisfies(e -> assertThat(e.type()).isEqualTo("DELAY_CLEARED"));
        assertThat(FlightView.of(store.flights.get("WS410")).status()).isEqualTo("ON_TIME");
    }

    @Test
    void delayOutsideTheAllowedRangeIsRejected() {
        assertThatThrownBy(() -> service.delay("AC123", -5)).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> service.delay("AC123", FlightService.MAX_DELAY_MINUTES + 1))
                .isInstanceOf(ResponseStatusException.class);
        assertThat(store.events).isEmpty();
    }

    @Test
    void viewMatchesTheShapeBoardingApiExpects() {
        FlightView v = FlightView.of(store.flights.get("AC123"));

        assertThat(v.flight()).isEqualTo("AC123");
        assertThat(v.gate()).isEqualTo("A1");
        assertThat(v.destination()).isEqualTo("YYZ");
        assertThat(v.departs()).isEqualTo("09:00");
        assertThat(v.capacity()).isEqualTo(150);
        assertThat(v.group()).isEqualTo(2);
    }
}
