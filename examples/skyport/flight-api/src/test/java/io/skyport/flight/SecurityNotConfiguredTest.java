package io.skyport.flight;

import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

/** With no JWKS URL configured (outside the cluster) nothing is enforced, and startup logs a warning. */
@WebMvcTest({FlightController.class, WhoAmIController.class})
@Import(SecurityConfig.class)
class SecurityNotConfiguredTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    FlightService service;

    @Test
    void withNoJwksUrlNothingIsEnforced() throws Exception {
        given(service.get("AC123")).willReturn(SecurityConfigTest.ac123());
        mvc.perform(get("/api/flights/AC123")).andExpect(status().isOk());
    }
}
