"""Measure download throughput with ten sequential HTTP requests."""

import argparse
import math
import sys
import time
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

REQUEST_COUNT = 10
CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class Measurement:
    elapsed: float
    size_bytes: int

    @property
    def mbps(self) -> float:
        return self.size_bytes * 8 / self.elapsed / 1_000_000


def http_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError
        parsed.port  # Validate the optional port as well.
        if parsed.username is not None or parsed.password is not None:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("Provide an HTTP(S) URL without credentials.") from None
    return value


def positive_timeout(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Timeout must be a positive number.") from None
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Timeout must be a positive finite number.")
    return number


def download(url: str, timeout: float) -> Measurement:
    request = Request(url, headers={
        "User-Agent": "internet-speed-meter/1.0",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    size = 0
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError(f"Expected HTTP 200, received HTTP {response.status}.")
        while chunk := response.read(CHUNK_SIZE):
            size += len(chunk)
        elapsed = time.perf_counter() - started
        declared_size = response.headers.get("Content-Length")
        if declared_size is not None and size != int(declared_size):
            raise ValueError("Incomplete response: downloaded size differs from Content-Length.")
    if not size:
        raise ValueError("The response body is empty.")
    if elapsed <= 0:
        raise ValueError("The timer could not measure the request duration.")
    return Measurement(elapsed, size)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download a URL 10 times sequentially and measure speed in Mbit/s."
    )
    parser.add_argument("url", type=http_url, help="Direct URL to a large image or other file")
    parser.add_argument("--timeout", type=positive_timeout, default=30.0,
                        help="Socket operation timeout in seconds (default: 30)")
    args = parser.parse_args(argv)

    measurements = []
    for index in range(1, REQUEST_COUNT + 1):
        try:
            result = download(args.url, args.timeout)
        except (URLError, OSError, HTTPException, ValueError) as error:
            print(f"Request {index}/{REQUEST_COUNT} failed: {error}", file=sys.stderr)
            print("Measurement stopped; no final speed calculated.", file=sys.stderr)
            return 1
        measurements.append(result)
        print(f"[{index:02d}/{REQUEST_COUNT}] {result.elapsed:.3f} s | "
              f"{result.size_bytes:,} bytes | {result.mbps:.2f} Mbit/s", flush=True)

    total_time = sum(item.elapsed for item in measurements)
    total_size = sum(item.size_bytes for item in measurements)
    print(f"\nCompleted requests: {len(measurements)}")
    print(f"Average request time: {total_time / REQUEST_COUNT:.3f} s")
    print(f"Downloaded: {total_size:,} bytes ({total_size / 1_000_000:.3f} MB)")
    print(f"Download speed: {total_size * 8 / total_time / 1_000_000:.2f} Mbit/s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nMeasurement interrupted.", file=sys.stderr)
        sys.exit(130)
