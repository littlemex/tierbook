"""A recording pass-through in front of an OpenAI-compatible engine, so what an agent SENDS is data.

The question this exists to answer is what a coding agent actually puts on the wire. Four agents point
at one Service alias and reach one model; whatever differs between them in cost, latency and solve rate
is the agent's contribution, and the first thing to know about that contribution is its content. Nobody
can read it off the agents' configs -- their configs set a base URL and almost nothing else, and every
sampling default, tool schema, context-management rule and retry policy is inside the binary.

It also settles a live confound. The billing gateway in front of the paid tiers honours some
OpenAI-shaped fields on one upstream wire and silently drops them on the other. If one agent sends
`reasoning_effort` and another does not, then "the agent effect" measured across models would partly be
"which agent happened to send a field this wire discards". That is unfalsifiable from the outside and
mechanical from here: record the bodies, and the confound becomes a column.

Two properties are load-bearing and the code is arranged around them.

**The request is forwarded byte-identically.** Not re-serialised from a parsed object, not with a header
normalised, not with a field dropped. A tap that edits its subject is an experimental artifact. The body
is read as bytes, recorded as bytes, and written upstream as the same bytes.

**Recording never affects the traffic.** Every write to the log is inside a try/except that swallows,
because a full disk must degrade to "we lost some observations" and never to "the agents stopped
working". The same rule applies to the log's own rotation.

Streaming is proxied chunk-by-chunk and flushed on every chunk. Buffering a response to record it would
destroy the time-to-first-token this is partly here to measure, and would change the agent's own
behaviour: several of these agents render tokens as they arrive and decide when to stop reading.

Stdlib only, matching the tools already in this cluster, so the image is a plain python base with no
wheel to build and nothing to audit.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import uuid
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM = os.environ.get("AGENT_TAP_UPSTREAM", "vllm-qwen-qwen3-6-35b-a3b-fp8:8000")
LOG_DIR = Path(os.environ.get("AGENT_TAP_LOG_DIR", "/data/agent-tap"))
# Full response bodies are the bulk of the traffic and almost none of the signal: the usage block, the
# finish reason and the timings are what a cost or latency figure is built from. A sample is kept anyway,
# because "the agent sent this and got that" is the only way to check a decoding claim later.
SAMPLE_RESPONSE_EVERY = int(os.environ.get("AGENT_TAP_SAMPLE_RESPONSE_EVERY", "50"))
MAX_BODY_BYTES = int(os.environ.get("AGENT_TAP_MAX_BODY_BYTES", str(8 * 1024 * 1024)))
# Hop-by-hop headers are per-connection by definition and forwarding them corrupts the next hop.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}

_lock = threading.Lock()
_counter = 0
_peer_names: dict[str, str] = {}


def _peer_label(ip: str) -> str:
    """Which agent this was, resolved from the pod IP and cached.

    Reverse DNS on a cluster IP gives the pod's own name, which is the cheapest identity available: it
    needs no header the agent would have to be modified to send, and modifying the agent is exactly what
    this measurement must not do. Cached because a lookup per request would put a DNS round trip inside
    the latency being measured, and unresolvable stays unresolvable rather than being retried forever.
    """
    if ip in _peer_names:
        return _peer_names[ip]
    label = ip
    try:
        label = socket.gethostbyaddr(ip)[0]
    except OSError:
        pass
    _peer_names[ip] = label
    return label


def _record(row: dict) -> None:
    """Append one observation. Never raises: see the module docstring."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # One file per day per pod. Per pod because two replicas appending to one file over NFS
        # interleave partial lines; per day so a reader can bound what it loads.
        name = f"tap-{time.strftime('%Y%m%d')}-{os.environ.get('HOSTNAME', 'local')}.jsonl"
        with (LOG_DIR / name).open("a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 -- deliberate: observation loss beats traffic loss
        pass


class Tap(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # The default logger writes a line per request to stderr, which on this traffic is noise that
    # buries a real error. Observations go to the log; only failures go to stderr.
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def _relay(self, method: str) -> None:
        global _counter

        body = b""
        length = self.headers.get("Content-Length")
        if length:
            try:
                n = int(length)
            except ValueError:
                self.send_error(400, "bad Content-Length")
                return
            if n > MAX_BODY_BYTES:
                # Refused rather than truncated: a truncated body forwarded upstream is a corrupted
                # request, and a truncated body recorded is a lie about what the agent sent.
                self.send_error(413, "body too large for the tap")
                return
            body = self.rfile.read(n)
        elif (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            body = self._read_chunked()

        request_id = uuid.uuid4().hex[:16]
        peer = _peer_label(self.client_address[0])
        t0 = time.monotonic()

        # Parsed only to pull out the few fields a reader wants indexed. The forwarded bytes are `body`,
        # untouched; a parse failure costs an index column and nothing else.
        parsed = None
        if body[:1] in (b"{", b"["):
            try:
                parsed = json.loads(body)
            except Exception:  # noqa: BLE001
                parsed = None

        headers = [(k, v) for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP]
        try:
            conn = HTTPConnection(UPSTREAM, timeout=1800)
            conn.putrequest(method, self.path, skip_host=True, skip_accept_encoding=True)
            for k, v in headers:
                conn.putheader(k, v)
            if body:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders()
            if body:
                conn.send(body)
            upstream = conn.getresponse()
        except Exception as exc:  # noqa: BLE001
            _record({
                "id": request_id, "ts": time.time(), "agent": peer, "method": method,
                "path": self.path, "request": parsed, "request_bytes": len(body),
                "error": f"{type(exc).__name__}: {exc}"[:300],
            })
            print(f"[tap] upstream failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            self.send_error(502, "upstream unreachable")
            return

        self.send_response(upstream.status)
        streaming = False
        for k, v in upstream.getheaders():
            if k.lower() in HOP_BY_HOP or k.lower() == "content-length":
                continue
            if k.lower() == "content-type" and "event-stream" in v.lower():
                streaming = True
            self.send_header(k, v)
        # Length is unknown once chunks are relayed as they arrive, so the response is framed as chunked
        # in both directions rather than buffered to compute one.
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        ttfb = None
        total = 0
        tail = b""
        with _lock:
            _counter += 1
            sample = SAMPLE_RESPONSE_EVERY > 0 and _counter % SAMPLE_RESPONSE_EVERY == 0
        sampled = bytearray() if sample else None

        while True:
            # `read1`, not `read`. `HTTPResponse.read(n)` is a buffered read that blocks until it has n
            # bytes or the stream ends, so with 8 KiB and ~50-byte SSE frames it returns once, at the
            # end, having buffered the entire completion. That destroys time-to-first-token -- which is
            # half of what this tap measures -- and it also changes the agents' own behaviour, since
            # several of them render tokens as they arrive and decide when to stop reading. `read1`
            # returns whatever is available. A test asserts the gap between first byte and last.
            chunk = upstream.read1(8192)
            if not chunk:
                break
            if ttfb is None:
                ttfb = time.monotonic() - t0
            total += len(chunk)
            # The last stretch is where a stream's usage block and finish reason live, so a bounded
            # window of the end is kept for every request while the middle is not.
            tail = (tail + chunk)[-16384:]
            if sampled is not None and len(sampled) < MAX_BODY_BYTES:
                sampled.extend(chunk)
            try:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                # The agent stopped reading. That is an observation -- an abandoned stream is billed
                # upstream all the same -- so it is recorded rather than treated as an error.
                _record(self._row(request_id, peer, method, parsed, len(body), upstream.status,
                                  ttfb, total, t0, tail, streaming, sampled,
                                  note="client disconnected mid-stream"))
                conn.close()
                return
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        conn.close()
        _record(self._row(request_id, peer, method, parsed, len(body), upstream.status,
                          ttfb, total, t0, tail, streaming, sampled))

    def _row(self, request_id, peer, method, parsed, req_bytes, status, ttfb, total, t0,
             tail, streaming, sampled, note=None) -> dict:
        row = {
            "id": request_id,
            "ts": time.time(),
            "agent": peer,
            "method": method,
            "path": self.path,
            "status": status,
            "streaming": streaming,
            # The whole request, as sent. This is the point of the tap: the fields, the tool schemas,
            # the system prompt and how the conversation grows are all in here.
            "request": parsed,
            "request_bytes": req_bytes,
            "response_bytes": total,
            "ttfb_ms": round(ttfb * 1000, 1) if ttfb is not None else None,
            "total_ms": round((time.monotonic() - t0) * 1000, 1),
        }
        if note:
            row["note"] = note
        usage = _usage_from_tail(tail)
        if usage is not None:
            row["usage"] = usage
        if sampled is not None:
            row["response_sample"] = sampled.decode("utf-8", "replace")
        return row

    def _read_chunked(self) -> bytes:
        out = bytearray()
        while True:
            line = self.rfile.readline().strip()
            if not line:
                break
            try:
                size = int(line.split(b";")[0], 16)
            except ValueError:
                break
            if size == 0:
                self.rfile.readline()
                break
            out.extend(self.rfile.read(size))
            self.rfile.readline()
            if len(out) > MAX_BODY_BYTES:
                break
        return bytes(out)

    def do_POST(self) -> None:  # noqa: N802
        self._relay("POST")

    def do_GET(self) -> None:  # noqa: N802
        self._relay("GET")


def _usage_from_tail(tail: bytes) -> dict | None:
    """The usage block, from the end of either response shape.

    Streamed: the last `data:` frame carrying one. Non-streamed: the single JSON body, whose end is in
    the window. Read from the tail rather than from a full buffer so the middle of a long completion is
    never held in memory.
    """
    text = tail.decode("utf-8", "replace")
    if '"usage"' not in text:
        return None
    for frame in reversed(text.split("data:")):
        frame = frame.strip()
        if not frame or frame == "[DONE]":
            continue
        start = frame.find("{")
        if start < 0:
            continue
        try:
            obj = json.loads(frame[start:])
        except Exception:  # noqa: BLE001 -- a truncated frame at the window edge is expected
            continue
        if isinstance(obj, dict) and obj.get("usage"):
            return obj["usage"]
    return None


def main() -> None:
    port = int(os.environ.get("AGENT_TAP_PORT", "8000"))
    print(f"[tap] :{port} -> {UPSTREAM}, log {LOG_DIR}", file=sys.stderr, flush=True)
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer(("0.0.0.0", port), Tap).serve_forever()


if __name__ == "__main__":
    main()
