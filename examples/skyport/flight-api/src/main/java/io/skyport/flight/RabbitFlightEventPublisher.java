package io.skyport.flight;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Publishes to a topic exchange on the shared broker. The exchange is declared here, so the
 * producer's broker permissions (configure + write on that one exchange) are all it needs.
 */
@Component
@ConditionalOnProperty(name = "events.enabled", havingValue = "true")
public class RabbitFlightEventPublisher implements FlightEventPublisher {

    private static final Logger log = LoggerFactory.getLogger(RabbitFlightEventPublisher.class);

    @Configuration
    @ConditionalOnProperty(name = "events.enabled", havingValue = "true")
    static class Wiring {

        @Bean
        TopicExchange flightEventsExchange(@Value("${events.exchange}") String name) {
            return new TopicExchange(name, true, false);
        }

        @Bean
        Jackson2JsonMessageConverter flightEventsConverter(ObjectMapper mapper) {
            return new Jackson2JsonMessageConverter(mapper);
        }
    }

    private final RabbitTemplate template;
    private final String exchange;

    public RabbitFlightEventPublisher(RabbitTemplate template, TopicExchange flightEventsExchange) {
        this.template = template;
        this.exchange = flightEventsExchange.getName();
    }

    @Override
    public void publish(FlightMessage message) {
        try {
            template.convertAndSend(exchange, message.routingKey(), message);
        } catch (RuntimeException e) {
            // The change is already committed; losing one notification is better than failing it.
            log.warn("could not publish {} to exchange {}: {}", message.routingKey(), exchange, e.toString());
        }
    }
}
