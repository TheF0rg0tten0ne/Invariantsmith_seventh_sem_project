"""Client-side config. Kept tiny and separate from server/config.py -- the
client is a separate process talking to the server purely over HTTP."""

API_BASE_URL = "http://127.0.0.1:8731"

# Must match server/config.py::LIVE_ANALYSIS_DEBOUNCE_MS -- client and
# server agree on this contract so the debounce feels consistent even
# though only the client actually enforces it.
LIVE_ANALYSIS_DEBOUNCE_MS = 250

# Must stay >= server/config.py::LLAMA_TIMEOUT_CEILING_S (the hard ceiling
# the server itself ever waits on one model call). The server sizes its
# own internal timeout per-request based on file size (small file: fast;
# large file: proportionally longer, up to that ceiling) -- but if the
# HTTP client's read timeout is shorter than the server's own ceiling, the
# client gives up and drops the connection while the server is still
# legitimately working within its own budget. That mismatch is exactly
# what produced "Read timed out. (read timeout=60)" on a large file: the
# server had correctly given itself more room to work, but the client cut
# the socket at a flat 60s regardless. A few seconds of margin above the
# server's ceiling accounts for network/serialization overhead on top of
# the server's own internal wait.
MODEL_REQUEST_TIMEOUT_S = 250

DEFAULT_THEME = "invariant_gold"
