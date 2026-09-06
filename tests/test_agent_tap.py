"""The tap must not change what it observes, and must not lose the traffic to observe it.

Run against a fake upstream on localhost, because the two properties worth testing are both about the
bytes on the wire and neither is visible from a unit test of a function.
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


SEEN: list[dict] = []


class Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # noqa: A003
        return

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        # `get_all`, not `dict(...)`: a duplicated header collapses in a dict and that is precisely the
        # defect this fake failed to catch. BaseHTTPRequestHandler accepts two Content-Length headers
        # and reads the first; uvicorn answers `400 Invalid HTTP request received`.
        SEEN.append({"raw": raw, "headers": dict(self.headers), "path": self.path,
                     "content_lengths": self.headers.get_all("Content-Length") or []})
        if b'"stream": true' in raw or b'"stream":true' in raw:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            frames = [
                b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n',
                b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n',
                b'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":2,'
                b'"total_tokens":13,"cache_read_input_tokens":7}}\n\n',
                b"data: [DONE]\n\n",
            ]
            for f in frames:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(f), f))
                self.wfile.flush()
                time.sleep(0.02)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return
        payload = json.dumps({
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture(scope="module")
def tap():
    up_port, tap_port = _free_port(), _free_port()
    logdir = tempfile.mkdtemp()
    os.environ["AGENT_TAP_UPSTREAM"] = f"127.0.0.1:{up_port}"
    os.environ["AGENT_TAP_LOG_DIR"] = logdir
    os.environ["AGENT_TAP_SAMPLE_RESPONSE_EVERY"] = "0"
    import agent_tap  # noqa: PLC0415  (imported after the env it reads at module scope)

    ThreadingHTTPServer.daemon_threads = True
    up = ThreadingHTTPServer(("127.0.0.1", up_port), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    tp = ThreadingHTTPServer(("127.0.0.1", tap_port), agent_tap.Tap)
    threading.Thread(target=tp.serve_forever, daemon=True).start()
    time.sleep(0.2)
    yield f"http://127.0.0.1:{tap_port}", Path(logdir)
    up.shutdown()
    tp.shutdown()


def _post(base: str, body: dict, stream: bool = False) -> bytes:
    raw = json.dumps(body).encode()
    req = urllib.request.Request(f"{base}/v1/chat/completions", data=raw,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer sk-noop"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _rows(logdir: Path) -> list[dict]:
    out = []
    for p in sorted(logdir.glob("*.jsonl")):
        out += [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
    return out


def test_the_request_reaches_upstream_byte_identically(tap):
    """The property the whole measurement rests on.

    A tap that re-serialises a parsed body changes key order, drops an unknown field, or normalises a
    number, and then the thing being recorded is the tap's opinion of the request rather than the
    request. Non-obvious fields are included on purpose: `reasoning_effort` is exactly the kind of
    extra a gateway drops on one wire, so it must survive this hop to be observable at all.
    """
    SEEN.clear()
    base, _ = tap
    body = {"model": "m", "messages": [{"role": "user", "content": "x"}],
            "reasoning_effort": "high", "seed": 7, "parallel_tool_calls": False,
            "zzz_unknown_field": {"nested": [1, 2, 3]}}
    sent = json.dumps(body).encode()
    _post(base, body)
    assert len(SEEN) == 1
    assert SEEN[0]["raw"] == sent, "the tap altered the request body"
    assert SEEN[0]["path"] == "/v1/chat/completions"
    # Caller headers travel too: an agent's auth and content type are part of what it sends.
    assert SEEN[0]["headers"].get("Authorization") == "Bearer sk-noop"


def test_a_non_streamed_reply_is_returned_and_its_usage_recorded(tap):
    base, logdir = tap
    out = _post(base, {"model": "m", "messages": [{"role": "user", "content": "x"}]})
    assert json.loads(out)["choices"][0]["message"]["content"] == "hi"
    row = _rows(logdir)[-1]
    assert row["usage"]["total_tokens"] == 6
    assert row["status"] == 200
    assert row["request"]["model"] == "m"


def test_a_stream_is_relayed_whole_and_its_terminal_usage_recorded(tap):
    """Including the cache leg, which is the field a cost figure needs and the one a buffering
    proxy is most likely to lose by reading only the first frame."""
    base, logdir = tap
    out = _post(base, {"model": "m", "messages": [{"role": "user", "content": "x"}], "stream": True})
    assert b"hello" in out.replace(b'data: {"choices":[{"delta":{"content":"', b"").replace(b'"}}]}\n\n', b"")
    assert out.count(b"data:") == 4 and out.rstrip().endswith(b"[DONE]")
    row = _rows(logdir)[-1]
    assert row["streaming"] is True
    assert row["usage"]["cache_read_input_tokens"] == 7
    assert row["usage"]["completion_tokens"] == 2


def test_the_stream_is_not_buffered(tap):
    """A buffered relay destroys time-to-first-token, which is one of the things being measured.

    The fake upstream sleeps 20ms between four frames, so a relay that waits for the end reports a
    first-byte time at or past the total. Asserted as a gap rather than an absolute, so a slow CI box
    cannot fail it.
    """
    base, logdir = tap
    _post(base, {"model": "m", "messages": [{"role": "user", "content": "x"}], "stream": True})
    row = _rows(logdir)[-1]
    assert row["ttfb_ms"] is not None
    assert row["ttfb_ms"] < row["total_ms"] - 30, (row["ttfb_ms"], row["total_ms"])


def test_the_caller_is_identified_without_asking_it_to_cooperate(tap):
    # Whatever the label resolves to, it must be present and stable: the agent cannot be modified to
    # send a header, so identity has to come from the connection.
    base, logdir = tap
    _post(base, {"model": "m", "messages": [{"role": "user", "content": "x"}]})
    rows = _rows(logdir)
    assert rows[-1]["agent"]
    assert len({r["agent"] for r in rows}) == 1


def test_recording_failure_does_not_break_the_traffic(tap, monkeypatch):
    """The rule the module is arranged around: observation loss beats traffic loss."""
    base, _ = tap
    import agent_tap  # noqa: PLC0415

    def explode(_row):
        raise OSError("disk full")

    monkeypatch.setattr(agent_tap, "_record", explode)
    with pytest.raises(OSError):
        agent_tap._record({})          # the fault is real
    out = _post(base, {"model": "m", "messages": [{"role": "user", "content": "x"}]})
    assert json.loads(out)["choices"][0]["finish_reason"] == "stop"


def test_exactly_one_content_length_reaches_upstream(tap):
    """The bug a permissive fake upstream hid.

    The tap copies the caller's headers and then sets `Content-Length` from the body it is actually
    sending. Copying the caller's as well sends the header twice, which Python's own
    `BaseHTTPRequestHandler` tolerates by reading the first value and uvicorn rejects outright -- vLLM
    behind it answered every POST with `400 Invalid HTTP request received` while this suite was green.
    """
    SEEN.clear()
    base, _ = tap
    _post(base, {"model": "m", "messages": [{"role": "user", "content": "x"}]})
    assert SEEN[0]["content_lengths"] == [str(len(SEEN[0]["raw"]))], SEEN[0]["content_lengths"]
