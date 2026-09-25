package io.skyport.flight;

import static org.assertj.core.api.Assertions.assertThat;

import javax.sql.DataSource;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/**
 * Runs the real migrations and queries against a real Postgres. Skipped unless TEST_DB_URL is
 * set (CI has no database), so `./test.sh` stays self-contained. Locally:
 * TEST_DB_URL=jdbc:postgresql://localhost:5432/flight_db TEST_DB_USER=... TEST_DB_PASSWORD=... ./mvnw test
 */
@EnabledIfEnvironmentVariable(named = "TEST_DB_URL", matches = ".+")
class FlightRepositoryIT {

    static FlightRepository repo;
    static FlightService service;
    static JdbcClient db;

    @BeforeAll
    static void migrate() {
        DataSource ds = new DriverManagerDataSource(System.getenv("TEST_DB_URL"), System.getenv("TEST_DB_USER"),
                System.getenv("TEST_DB_PASSWORD"));
        Flyway.configure().dataSource(ds).cleanDisabled(false).load().clean();
        Flyway.configure().dataSource(ds).load().migrate();
        db = JdbcClient.create(ds);
        repo = new FlightRepository(db);
        service = new FlightService(repo);
    }

    @Test
    void migrationsSeedTheFlights() {
        assertThat(repo.all()).hasSizeGreaterThanOrEqualTo(20);
        assertThat(repo.find("AC123")).isPresent();
    }

    @Test
    void gateChangeAndEventAreStoredAndReadBack() {
        String before = repo.find("AC456").orElseThrow().gate();
        String target = before.equals("D5") ? "C3" : "D5";

        service.changeGate("AC456", target);

        assertThat(repo.find("AC456").orElseThrow().gate()).isEqualTo(target);
        assertThat(repo.events("AC456", 5)).first().satisfies(e -> {
            assertThat(e.type()).isEqualTo("GATE_CHANGED");
            assertThat(e.detail()).isEqualTo(before + " -> " + target);
            assertThat(e.occurredAt()).isNotNull();
        });
    }

    @Test
    void delayIsStoredAndTheEventLogIsNewestFirst() {
        service.delay("AC789", 30);
        service.delay("AC789", 45);

        assertThat(repo.find("AC789").orElseThrow().delayMinutes()).isEqualTo(45);
        assertThat(repo.events("AC789", 5)).extracting(FlightEvent::detail).startsWith("30 -> 45 min");
    }

    @Test
    void databaseRejectsANegativeDelayEvenIfTheServiceWouldNot() {
        org.junit.jupiter.api.Assertions.assertThrows(Exception.class, () -> repo.setDelay("AC101", -1));
    }
}
