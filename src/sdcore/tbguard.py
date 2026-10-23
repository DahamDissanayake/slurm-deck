"""Token guard in front of TensorBoard, which has no authentication of its own.

Runs inside the TensorBoard job: listens on the node address and forwards to
TensorBoard on 127.0.0.1, refusing (401) any request whose X-SD-Token header
doesn't match the job's token. Only the session proxy knows the token.
Standard library only: deck-agent copies this file into the job folder and the
job runs it as `python3 tbguard.py`, with the token in $SD_TOKEN so it never
appears on a command line.
"""

from __future__ import annotations

import argparse
import hmac
import http.client
import http.server
import os

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailer", "transfer-encoding", "upgrade", "host", "x-sd-token"}
CHUNK = 64 * 1024


def make_server(listen: tuple[str, int], upstream: tuple[str, int],
                token: str) -> http.server.ThreadingHTTPServer:
    if not token:
        raise ValueError("a token is required")
    expected = token.encode()

    class Guard(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _forward(self) -> None:
            given = self.headers.get("X-SD-Token", "").encode()
            if not hmac.compare_digest(given, expected):
                self._reply(401, b"Unauthorized")
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            conn = http.client.HTTPConnection(*upstream, timeout=60)
            try:
                conn.request(self.command, self.path, body=body, headers=headers)
                resp = conn.getresponse()
            except OSError:
                conn.close()
                self._reply(502, b"TensorBoard is not responding")
                return
            try:
                self.send_response(resp.status, resp.reason)
                for k, v in resp.getheaders():
                    if k.lower() not in HOP_BY_HOP and k.lower() != "content-length":
                        self.send_header(k, v)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while chunk := resp.read(CHUNK):
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.write(b"0\r\n\r\n")
            finally:
                conn.close()

        def _reply(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _forward

        def do_HEAD(self) -> None:
            self._reply(405, b"")

        def log_message(self, format: str, *args: object) -> None:
            pass   # no access log: paths could carry the token in a query string

    return http.server.ThreadingHTTPServer(listen, Guard)


def _addr(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    return host, int(port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", required=True, help="host:port to serve on")
    parser.add_argument("--upstream", required=True, help="host:port of TensorBoard")
    parser.add_argument("--token", default=os.environ.get("SD_TOKEN", ""),
                        help="defaults to $SD_TOKEN")
    args = parser.parse_args(argv)
    make_server(_addr(args.listen), _addr(args.upstream), args.token).serve_forever()


if __name__ == "__main__":
    main()
