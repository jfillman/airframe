# Redis render fixtures

`fresh` renders the Release with nothing observed (`ComponentReady=False/RedisProvisioning`);
`deployed` observes the Release at Helm state `deployed` (`RedisReady`, XR `Ready`). The Release's
`writeConnectionSecretToRef` and `connectionDetails` are what `xrds/redis.meta.yaml`'s `{name}-connection`
outputs depend on; tools/test_sidecars.py checks them against these renders.
