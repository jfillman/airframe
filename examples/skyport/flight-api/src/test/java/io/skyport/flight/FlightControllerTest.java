package io.skyport.flight;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.LocalTime;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.server.ResponseStatusException;

@WebMvcTest({FlightController.class, WhoAmIController.class})
@Import({SecurityConfig.class, TestTokens.Decoder.class})
@TestPropertySource(properties = {"skyport.auth.jwks-url=http://jwks.invalid/keys",
        "skyport.auth.issuer=" + TestTokens.ISSUER})
class FlightControllerTest {

    private static final String AUTH = "Authorization";

    private static String bearer() {
        return "Bearer " + TestTokens.valid();
    }

    @Autowired
    MockMvc mvc;

    @MockBean
    FlightService service;

    private static Flight ac123() {
        return new Flight("AC123", "YVR", "YYZ", "A1", LocalTime.of(9, 0), 15, 150, 2);
    }

    @Test
    void getReturnsTheFlightInBoardingApisShape() throws Exception {
        given(service.get("AC123")).willReturn(ac123());

        mvc.perform(get("/api/flights/AC123").header(AUTH, bearer()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.flight").value("AC123"))
                .andExpect(jsonPath("$.gate").value("A1"))
                .andExpect(jsonPath("$.destination").value("YYZ"))
                .andExpect(jsonPath("$.departs").value("09:00"))
                .andExpect(jsonPath("$.estimatedDeparture").value("09:15"))
                .andExpect(jsonPath("$.status").value("DELAYED"))
                .andExpect(jsonPath("$.capacity").value(150))
                .andExpect(jsonPath("$.group").value(2));
    }

    @Test
    void unknownFlightIs404() throws Exception {
        given(service.get("AC999")).willThrow(new ResponseStatusException(HttpStatus.NOT_FOUND, "no such flight"));

        mvc.perform(get("/api/flights/AC999").header(AUTH, bearer())).andExpect(status().isNotFound());
    }

    @Test
    void gateChangeReturnsTheUpdatedFlight() throws Exception {
        given(service.changeGate("AC123", "B2"))
                .willReturn(new Flight("AC123", "YVR", "YYZ", "B2", LocalTime.of(9, 0), 0, 150, 2));

        mvc.perform(put("/api/flights/AC123/gate").header(AUTH, bearer()).contentType(MediaType.APPLICATION_JSON).content("{\"gate\":\"B2\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.gate").value("B2"));
    }

    @Test
    void invalidGateIs400() throws Exception {
        given(service.changeGate("AC123", "Z99"))
                .willThrow(new ResponseStatusException(HttpStatus.BAD_REQUEST, "bad gate"));

        mvc.perform(put("/api/flights/AC123/gate").header(AUTH, bearer()).contentType(MediaType.APPLICATION_JSON).content("{\"gate\":\"Z99\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void whoamiNamesTheServiceAndVersion() throws Exception {
        mvc.perform(get("/api/whoami"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.service").value("flight-api"))
                .andExpect(jsonPath("$.version").exists())
                .andExpect(jsonPath("$.database").value("postgresql"));
    }
}
