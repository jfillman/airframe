package io.skyport.flight;

import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.RSASSASigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.NoSuchAlgorithmException;
import java.security.interfaces.RSAPublicKey;
import java.time.Instant;
import java.util.Date;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;

/**
 * A locally generated RSA key standing in for Dex's: the decoder trusts it, and tests mint RS256
 * tokens with it (or with a second key the decoder does not trust).
 */
final class TestTokens {

    static final String ISSUER = "http://skyport-auth.app-skyport-auth-dev.svc.cluster.local:5556/dex";
    static final KeyPair TRUSTED = rsa();
    static final KeyPair UNTRUSTED = rsa();

    private TestTokens() {
    }

    static String valid() {
        return sign(TRUSTED, ISSUER, Instant.now().plusSeconds(300));
    }

    static String sign(KeyPair key, String issuer, Instant expires) {
        JWTClaimsSet claims = new JWTClaimsSet.Builder()
                .issuer(issuer)
                .subject("board-oauth")
                .audience("board-oauth")
                .issueTime(Date.from(Instant.now().minusSeconds(10)))
                .expirationTime(Date.from(expires))
                .build();
        SignedJWT jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).keyID("test").build(), claims);
        try {
            jwt.sign(new RSASSASigner(key.getPrivate()));
        } catch (JOSEException e) {
            throw new IllegalStateException(e);
        }
        return jwt.serialize();
    }

    private static KeyPair rsa() {
        try {
            KeyPairGenerator g = KeyPairGenerator.getInstance("RSA");
            g.initialize(2048);
            return g.generateKeyPair();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /** Replaces the JWKS-backed decoder: same validators, trusted key given directly. */
    @TestConfiguration
    static class Decoder {
        @Bean
        JwtDecoder jwtDecoder() {
            NimbusJwtDecoder d = NimbusJwtDecoder.withPublicKey((RSAPublicKey) TRUSTED.getPublic()).build();
            d.setJwtValidator(JwtValidators.createDefaultWithIssuer(ISSUER));
            return d;
        }
    }
}
