# shellcheck shell=bash
# Helpers for walkthrough steps that check Dex token enforcement (part 5, and part 4 once the API is
# protected). Source from a verify with:
#
#   . "$AIRFRAME_ROOT/docs/walkthroughs/lib/dex.sh"
#
# Read-only: kubectl port-forwards (on a free local port each), one client_credentials token request,
# GETs. Never prints a client secret. dex_token prints the access token on stdout so a step can
# capture it ($(dex_token ...)); a step must never echo it. The token is sent to curl on stdin, not as
# an argument, so it doesn't show in the process list.

# _wt_pf CTX NS SVC REMOTE_PORT: start a port-forward on a free local port; sets WT_PF_PID, WT_PF_PORT.
_wt_pf() {
  local log i
  log="$(mktemp)"
  kubectl --context "$1" port-forward -n "$2" "svc/$3" ":$4" >"$log" 2>&1 &
  WT_PF_PID=$!
  WT_PF_PORT=""
  for i in $(seq 1 75); do
    WT_PF_PORT="$(sed -n 's/^Forwarding from 127\.0\.0\.1:\([0-9][0-9]*\) .*/\1/p' "$log" | head -1)"
    [ -n "$WT_PF_PORT" ] && break
    if ! kill -0 "$WT_PF_PID" 2>/dev/null; then
      cat "$log" >&2
      rm -f "$log"
      return 1
    fi
    sleep 0.2
  done
  rm -f "$log"
  if [ -z "$WT_PF_PORT" ]; then
    echo "port-forward to $2/svc/$3 did not start" >&2
    kill "$WT_PF_PID" 2>/dev/null
    return 1
  fi
}

# dex_token CTX NAMESPACE ATTACH_NAME: an access token for the Dex attach client ATTACH_NAME in
# NAMESPACE (its Secret is ATTACH_NAME-oauth-credentials), minted through a port-forward to the Dex
# Service named in the Secret's token-url.
dex_token() {
  local ctx=$1 ns=$2 secret="$3-oauth-credentials" where rc pid
  where="$(CTX="$ctx" NS="$ns" SECRET="$secret" python3 - <<'PY'
import base64, json, os, re, subprocess, sys, urllib.parse
r = subprocess.run(["kubectl", "--context", os.environ["CTX"], "get", "secret", os.environ["SECRET"],
                    "-n", os.environ["NS"], "-o", "json"], capture_output=True, text=True)
if r.returncode:
    sys.exit(r.stderr.strip())
url = urllib.parse.urlparse(base64.b64decode(json.loads(r.stdout)["data"]["token-url"]).decode())
m = re.match(r"^([a-z0-9-]+)\.([a-z0-9-]+)\.svc(\.cluster\.local)?$", url.hostname or "")
if not m:
    sys.exit("token-url host %s is not an in-cluster Service" % url.hostname)
print(m.group(2), m.group(1), url.port or 80)
PY
)" || return 1
  # shellcheck disable=SC2086
  _wt_pf "$ctx" $where || return 1
  pid=$WT_PF_PID
  CTX="$ctx" NS="$ns" SECRET="$secret" BASE="http://127.0.0.1:$WT_PF_PORT" python3 - <<'PY'
import base64, json, os, subprocess, sys, urllib.error, urllib.parse, urllib.request
data = json.loads(subprocess.run(["kubectl", "--context", os.environ["CTX"], "get", "secret", os.environ["SECRET"],
                                  "-n", os.environ["NS"], "-o", "json"],
                                 check=True, capture_output=True, text=True).stdout)["data"]
d = {k: base64.b64decode(v).decode() for k, v in data.items()}
q = lambda s: urllib.parse.quote(s, safe="")
basic = base64.b64encode(("%s:%s" % (q(d["client-id"]), q(d["client-secret"]))).encode()).decode()
req = urllib.request.Request(os.environ["BASE"] + urllib.parse.urlparse(d["token-url"]).path,
                             data=b"grant_type=client_credentials", method="POST",
                             headers={"Content-Type": "application/x-www-form-urlencoded",
                                      "Authorization": "Basic " + basic})
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        tok = json.load(r).get("access_token")
except urllib.error.HTTPError as e:
    sys.exit("token endpoint answered %s" % e.code)
if not tok or tok.count(".") != 2:
    sys.exit("token endpoint answered without a JWT access_token")
print(tok)
PY
  rc=$?
  kill "$pid" 2>/dev/null
  return $rc
}

# _wt_get CTX NS SVC PORT PATH [TOKEN] FORMAT: curl through a port-forward; FORMAT is curl's -w or "body".
_wt_get() {
  local ctx=$1 ns=$2 svc=$3 port=$4 path=$5 tok=$6 fmt=$7 pid out rc
  _wt_pf "$ctx" "$ns" "$svc" "$port" || return 1
  pid=$WT_PF_PID
  local url="http://127.0.0.1:$WT_PF_PORT$path"
  if [ "$fmt" = body ]; then
    out="$(printf 'Authorization: Bearer %s\n' "$tok" | { if [ -n "$tok" ]; then curl -s --max-time 15 -H @- "$url"; else curl -s --max-time 15 "$url"; fi; })"
  else
    out="$(printf 'Authorization: Bearer %s\n' "$tok" | { if [ -n "$tok" ]; then curl -s --max-time 15 -o /dev/null -w "$fmt" -H @- "$url"; else curl -s --max-time 15 -o /dev/null -w "$fmt" "$url"; fi; })"
  fi
  rc=$?
  kill "$pid" 2>/dev/null
  printf '%s' "$out"
  return $rc
}

# http_status CTX NS SVC PORT PATH [TOKEN]: the HTTP status of GET PATH on the Service.
http_status() { _wt_get "$1" "$2" "$3" "$4" "$5" "${6:-}" '%{http_code}'; }

# http_body CTX NS SVC PORT PATH [TOKEN]: the body of GET PATH on the Service.
http_body() { _wt_get "$1" "$2" "$3" "$4" "$5" "${6:-}" body; }

# expect_enforced CTX NS SVC PORT PATH TOKEN: 401 without a token, 200 with it; prints both statuses.
expect_enforced() {
  local without with
  without="$(http_status "$1" "$2" "$3" "$4" "$5")" || return 1
  with="$(http_status "$1" "$2" "$3" "$4" "$5" "$6")" || return 1
  echo "$3 GET $5: without a token $without, with a token $with"
  [ "$without" = "401" ] && [ "$with" = "200" ]
}
