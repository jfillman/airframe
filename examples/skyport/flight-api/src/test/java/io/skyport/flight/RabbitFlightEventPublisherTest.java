package io.skyport.flight;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.AmqpConnectException;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

class RabbitFlightEventPublisherTest {

    private final FlightMessage message = new FlightMessage("AC123", "GATE_CHANGED", "A1 -> B2", "B2", 0,
            Instant.EPOCH);
    private final RabbitTemplate template = mock(RabbitTemplate.class);
    private final RabbitFlightEventPublisher publisher = new RabbitFlightEventPublisher(template,
            new TopicExchange("flights.events"));

    @Test
    void publishesToTheExchangeWithTheRoutingKey() {
        publisher.publish(message);

        verify(template).convertAndSend(eq("flights.events"), eq("flight.AC123.gate_changed"), eq(message));
    }

    @Test
    void aBrokerOutageIsSwallowedNotThrown() {
        doThrow(new AmqpConnectException(new RuntimeException("down")))
                .when(template).convertAndSend(anyString(), anyString(), any(Object.class));

        assertThatCode(() -> publisher.publish(message)).doesNotThrowAnyException();
    }
}
