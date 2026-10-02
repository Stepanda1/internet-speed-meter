import contextlib
import io
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import speed_meter

PAYLOAD = b"speed test\n" * 10000


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        server = self.server
        with server.lock:
            server.count += 1
            server.active += 1
            server.max_active = max(server.max_active, server.active)
            server.request_headers.append(self.headers)
        try:
            if self.path == "/error":
                self.send_error(503)
                return
            if self.path == "/slow":
                time.sleep(0.1)
            data = b"" if self.path == "/empty" else PAYLOAD
            self.send_response(200)
            self.send_header("Content-Length", str(len(data) + (1 if self.path == "/truncated" else 0)))
            self.end_headers()
            # Finish bookkeeping before sending the final bytes so overlap is measurable.
            self.wfile.write(data[:-1])
            self.wfile.flush()
            with server.lock:
                server.active -= 1
            if data:
                self.wfile.write(data[-1:])
        except OSError:
            with server.lock:
                server.active -= 1
        finally:
            if self.path == "/error":
                with server.lock:
                    server.active -= 1


class SpeedMeterTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.lock = threading.Lock()
        self.server.count = self.server.active = self.server.max_active = 0
        self.server.request_headers = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def run_cli(self, path, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = speed_meter.main([self.url + path, *extra])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_ten_sequential_downloads_and_total_bytes(self):
        code, output, errors = self.run_cli("/file")
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertEqual(self.server.count, 10)
        self.assertEqual(self.server.max_active, 1)
        self.assertEqual(output.count("Mbit/s"), 11)
        self.assertIn(f"Downloaded: {len(PAYLOAD) * 10:,} bytes", output)
        self.assertTrue(all(h["Accept-Encoding"] == "identity" for h in self.server.request_headers))
        self.assertTrue(all(h["Cache-Control"] == "no-cache" for h in self.server.request_headers))

    def test_download_counts_actual_bytes(self):
        result = speed_meter.download(self.url + "/file", 1)
        self.assertEqual(result.size_bytes, len(PAYLOAD))
        self.assertGreater(result.elapsed, 0)

    def test_aggregate_speed_uses_total_time(self):
        samples = [speed_meter.Measurement(1, 1_000_000), speed_meter.Measurement(3, 1_000_000)] * 5
        output = io.StringIO()
        with patch.object(speed_meter, "download", side_effect=samples), contextlib.redirect_stdout(output):
            self.assertEqual(speed_meter.main([self.url]), 0)
        self.assertIn("Average request time: 2.000 s", output.getvalue())
        self.assertIn("Download speed: 4.00 Mbit/s", output.getvalue())

    def test_failures_stop_without_final_result(self):
        for path in ("/error", "/empty", "/truncated"):
            with self.subTest(path=path):
                before = self.server.count
                code, output, errors = self.run_cli(path)
                self.assertEqual(code, 1)
                self.assertEqual(self.server.count, before + 1)
                self.assertNotIn("Download speed:", output)
                self.assertIn("Request 1/10 failed:", errors)

    def test_socket_timeout(self):
        code, output, errors = self.run_cli("/slow", "--timeout", "0.01")
        self.assertEqual(code, 1)
        self.assertNotIn("Download speed:", output)
        self.assertIn("failed:", errors)

    def test_invalid_arguments(self):
        cases = [["file:///tmp/file"], ["https://"], ["http://host:bad"],
                 ["http://user:password@host"], [self.url, "--timeout", "0"],
                 [self.url, "--timeout", "nan"], [self.url, "--timeout", "inf"]]
        for args in cases:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    speed_meter.main(args)
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
