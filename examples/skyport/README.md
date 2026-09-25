# Skyport demo code

Source for the Skyport demo system. The design, the service map and the build
phases are in [`docs/user/skyport-demo.md`](../../docs/user/skyport-demo.md).

| Directory | Stack | Status |
|---|---|---|
| [`boarding-api/`](boarding-api/) | `NodeJSApplication` | Built. Used by the [quickstart](../../docs/user/quickstart.md). |
| [`flight-api/`](flight-api/) | `SpringBootApplication` | Built. Used by [quickstart part 2](../../docs/user/quickstart-flight-api.md). |

Each directory is meant to be copied over the source repo Airframe scaffolds for
that service — not built or deployed from here. The quickstart shows the copy.
