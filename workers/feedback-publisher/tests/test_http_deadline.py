"""Actual loopback traffic; no external network or credentials."""
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import publisher
from feedback_http_deadline import request_deadline


@pytest.mark.parametrize('slow_part', ['headers', 'body'])
def test_slow_http_has_one_total_deadline_and_next_request_succeeds(slow_part):
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            calls.append(self.path)
            body = b'{"ok":true,"padding":"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}'
            headers = b'HTTP/1.0 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'
            try:
                if self.path == '/fast':
                    self.wfile.write(headers+body)
                    return
                for data, slow in [(headers, slow_part == 'headers'), (body, slow_part == 'body')]:
                    if not slow:
                        self.wfile.write(data); self.wfile.flush()
                    else:
                        for byte in data:
                            self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(.03)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    previous = signal.getsignal(signal.SIGALRM)
    try:
        start = time.monotonic()
        with pytest.raises(publisher.PublisherError) as caught:
            publisher._json_request(f'http://127.0.0.1:{server.server_port}/slow', timeout=.12)
        elapsed = time.monotonic() - start
        assert caught.value.category == 'transport_ambiguous'
        assert elapsed < .8
        assert signal.getitimer(signal.ITIMER_REAL) == (0., 0.)
        assert signal.getsignal(signal.SIGALRM) == previous
        assert publisher._json_request(f'http://127.0.0.1:{server.server_port}/fast')['ok'] is True
        assert calls == ['/slow', '/fast']
    finally:
        server.shutdown(); server.server_close(); thread.join(2)


def test_deadline_refuses_thread_and_nested_timer_without_overwriting_it():
    from concurrent.futures import ThreadPoolExecutor
    observed = []
    def background():
        with request_deadline(1): observed.append('unsafe')
    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(TimeoutError):
            executor.submit(background).result(timeout=2)
    assert observed == []
    previous = signal.getsignal(signal.SIGALRM)
    with request_deadline(2):
        handler = signal.getsignal(signal.SIGALRM)
        with pytest.raises(TimeoutError):
            with request_deadline(1): observed.append('nested')
        assert signal.getsignal(signal.SIGALRM) == handler
        assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
    assert observed == []
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL) == (0., 0.)
