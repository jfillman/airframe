package io.skyport.flight;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.time.LocalTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

/** What the part 5 walkthrough checks live: 401 without a valid Dex token, 200 with one, probes open. */
@WebMvcTest({FlightController.class, WhoAmIController.class})
@Import({SecurityConfig.class, TestTokens.Decoder.class})
@TestPropertySource(properties = {"skyport.auth.jwks-url=http://jwks.invalid/keys",
        "skyport.auth.issuer=" + TestTokens.ISSUER})
class SecurityConfigTest {

    static Flight ac123() {
        return new Flight("AC123", "YVR", "YYZ", "A1", LocalTime.of(9, 0), 0, 150, 2);
    }

    @Autowired
    MockMvc mvc;

    @MockBean
    FlightService service;

    @Test
    void noTokenIs401WithABearerChallenge() throws Exception {
        mvc.perform(get("/api/flights/AC123"))
                .andExpect(status().isUnauthorized())
                .andExpect(header().string("WWW-Authenticate", org.hamcrest.Matchers.startsWith("Bearer")));
    }

    @Test
    void listAndWritesNeedATokenToo() throws Exception {
        mvc.perform(get("/api/flights")).andExpect(status().isUnauthorized());
        mvc.perform(put("/api/flights/AC123/gate").contentType(MediaType.APPLICATION_JSON).content("{\"gate\":\"B2\"}"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void validTokenIs200() throws Exception {
        given(service.get("AC123")).willReturn(ac123());
        given(service.all()).willReturn(List.of(ac123()));
        mvc.perform(get("/api/flights/AC123").header("Authorization", "Bearer " + TestTokens.valid()))
                .andExpect(status().isOk());
        mvc.perform(get("/api/flights").header("Authorization", "Bearer " + TestTokens.valid()))
                .andExpect(status().isOk());
    }

    @Test
    void tokenSignedByAnotherKeyIs401() throws Exception {
        String forged = TestTokens.sign(TestTokens.UNTRUSTED, TestTokens.ISSUER, Instant.now().plusSeconds(300));
        mvc.perform(get("/api/flights/AC123").header("Authorization", "Bearer " + forged))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void tokenFromAnotherIssuerIs401() throws Exception {
        String other = TestTokens.sign(TestTokens.TRUSTED, "http://elsewhere/dex", Instant.now().plusSeconds(300));
        mvc.perform(get("/api/flights/AC123").header("Authorization", "Bearer " + other))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void expiredTokenIs401() throws Exception {
        String expired = TestTokens.sign(TestTokens.TRUSTED, TestTokens.ISSUER, Instant.now().minusSeconds(600));
        mvc.perform(get("/api/flights/AC123").header("Authorization", "Bearer " + expired))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void garbageTokenIs401() throws Exception {
        mvc.perform(get("/api/flights/AC123").header("Authorization", "Bearer not-a-jwt"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void whoamiStaysOpen() throws Exception {
        mvc.perform(get("/api/whoami")).andExpect(status().isOk());
    }

    @Test
    void healthPathsAreNotBehindAuth() throws Exception {
        // The actuator isn't part of this test slice, so these 404 here; the point is that the
        // security chain lets them through (never 401), which is what the probes need.
        for (String p : new String[]{"/actuator/health", "/actuator/health/liveness", "/actuator/health/readiness"}) {
            mvc.perform(get(p)).andExpect(result -> {
                int s = result.getResponse().getStatus();
                if (s == 401 || s == 403) {
                    throw new AssertionError(p + " answered " + s);
                }
            });
        }
    }
}
