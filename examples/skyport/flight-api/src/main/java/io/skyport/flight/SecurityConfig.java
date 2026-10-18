package io.skyport.flight;

import jakarta.servlet.DispatcherType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Bearer-token auth for the flight API (Skyport part 5): tokens are JWTs issued by the shared Dex
 * server (skyport-auth), checked against its published key set (JWKS), its issuer and their expiry.
 *
 * <p>Open, always: {@code /api/whoami} (the canary board polls it), {@code /actuator/health/**}
 * (liveness/readiness probes), {@code /error}. Protected when {@code skyport.auth.jwks-url} is set:
 * {@code /api/flights} and everything under it, every method. With no JWKS URL configured nothing
 * is enforced, so the app still runs outside the cluster; that is logged at startup.
 *
 * <p>Any valid Dex token is accepted: Dex's client_credentials grant has no per-client scopes, so
 * there is no finer rule to apply yet.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    private static final Logger log = LoggerFactory.getLogger(SecurityConfig.class);

    static final String[] OPEN = {"/api/whoami", "/actuator/health", "/actuator/health/**", "/actuator/info", "/error"};

    @Bean
    SecurityFilterChain apiSecurity(HttpSecurity http,
                                    @Value("${skyport.auth.jwks-url:}") String jwksUrl,
                                    @Value("${skyport.auth.issuer:}") String issuer,
                                    ObjectProvider<JwtDecoder> decoderOverride) throws Exception {
        // Bearer tokens only: no sessions, no cookies, so no CSRF surface.
        http.csrf(c -> c.disable())
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .httpBasic(b -> b.disable())
                .formLogin(f -> f.disable());

        if (jwksUrl == null || jwksUrl.isBlank()) {
            log.warn("skyport.auth.jwks-url (OAUTH_JWKS_URL) is not set: /api/flights is NOT protected");
            http.authorizeHttpRequests(a -> a.anyRequest().permitAll());
            return http.build();
        }

        JwtDecoder decoder = decoderOverride.getIfAvailable(() -> dexDecoder(jwksUrl, issuer));
        log.info("bearer tokens required on /api/flights (JWKS {}, issuer {})", jwksUrl,
                issuer == null || issuer.isBlank() ? "not checked" : issuer);
        http.authorizeHttpRequests(a -> a
                        .dispatcherTypeMatchers(DispatcherType.ERROR).permitAll()
                        .requestMatchers(OPEN).permitAll()
                        .requestMatchers("/api/flights", "/api/flights/**").authenticated()
                        .anyRequest().permitAll())
                .oauth2ResourceServer(o -> o.jwt(j -> j.decoder(decoder)));
        return http.build();
    }

    /** Signature from the JWKS (fetched lazily, cached), plus expiry and, when configured, issuer. */
    static JwtDecoder dexDecoder(String jwksUrl, String issuer) {
        NimbusJwtDecoder decoder = NimbusJwtDecoder.withJwkSetUri(jwksUrl).build();
        decoder.setJwtValidator(issuer == null || issuer.isBlank()
                ? JwtValidators.createDefault()
                : JwtValidators.createDefaultWithIssuer(issuer));
        return decoder;
    }
}
