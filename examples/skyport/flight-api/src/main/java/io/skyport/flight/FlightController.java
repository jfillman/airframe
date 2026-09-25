package io.skyport.flight;

import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/flights")
public class FlightController {

    public record GateRequest(String gate) {
    }

    public record DelayRequest(int minutes) {
    }

    private final FlightService flights;

    public FlightController(FlightService flights) {
        this.flights = flights;
    }

    @GetMapping
    public List<FlightView> list() {
        return flights.all().stream().map(FlightView::of).toList();
    }

    @GetMapping("/{flightNumber}")
    public FlightView get(@PathVariable String flightNumber) {
        return FlightView.of(flights.get(flightNumber));
    }

    @GetMapping("/{flightNumber}/events")
    public List<FlightEvent> events(@PathVariable String flightNumber,
                                    @RequestParam(defaultValue = "20") int limit) {
        return flights.events(flightNumber, limit);
    }

    @PutMapping("/{flightNumber}/gate")
    public FlightView changeGate(@PathVariable String flightNumber, @RequestBody GateRequest body) {
        return FlightView.of(flights.changeGate(flightNumber, body.gate()));
    }

    @PutMapping("/{flightNumber}/delay")
    public FlightView delay(@PathVariable String flightNumber, @RequestBody DelayRequest body) {
        return FlightView.of(flights.delay(flightNumber, body.minutes()));
    }
}
