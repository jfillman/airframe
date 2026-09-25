CREATE TABLE flights (
    flight_number       VARCHAR(6)   PRIMARY KEY,
    origin              CHAR(3)      NOT NULL,
    destination         CHAR(3)      NOT NULL,
    gate                VARCHAR(4)   NOT NULL,
    scheduled_departure TIME         NOT NULL,
    delay_minutes       INTEGER      NOT NULL DEFAULT 0 CHECK (delay_minutes >= 0),
    capacity            INTEGER      NOT NULL CHECK (capacity > 0),
    boarding_group      INTEGER      NOT NULL DEFAULT 1 CHECK (boarding_group BETWEEN 1 AND 5),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- One row per change to a flight. Written in the same transaction as the change, so it is
-- the durable record a broker can publish from later (Phase 2) without ever missing one.
CREATE TABLE flight_events (
    id            BIGSERIAL    PRIMARY KEY,
    flight_number VARCHAR(6)   NOT NULL REFERENCES flights (flight_number),
    event_type    VARCHAR(20)  NOT NULL,
    detail        VARCHAR(200) NOT NULL,
    occurred_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX flight_events_by_flight ON flight_events (flight_number, id DESC);
