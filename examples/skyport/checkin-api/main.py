import os
from http.server import ThreadingHTTPServer

from checkin import Handler

port = int(os.environ.get("PORT", "8080"))
print(f"checkin-api listening on {port}", flush=True)
ThreadingHTTPServer(("", port), Handler).serve_forever()
