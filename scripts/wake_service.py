#!/usr/bin/env python3
"""Tiny Wake-on-LAN HTTP service for .69 (nginx gateway).

Listens on localhost:9748. nginx routes /api/wake here.
When .111 is down, the frontend can POST /api/wake to power it on.

No external deps — stdlib only. Runs as a systemd service on .69.

Usage:
    python3 wake_service.py

systemd unit:
    [Unit]
    Description=Lost Landscapes Wake-on-LAN service
    After=network.target

    [Service]
    ExecStart=/usr/bin/python3 /opt/lost-landscapes/wake_service.py
    Restart=always
    User=noah

    [Install]
    WantedBy=multi-user.target
"""

import json
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 9748
TARGET_MAC = "00:e0:4c:68:00:95"
TARGET_IP = "192.168.1.111"
HEALTH_CHECK_PORT = 9747

# Rate limit: one wake per 60 seconds
_last_wake = 0.0


class WakeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/wake":
            self._handle_wake()
        else:
            self._send_json(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/api/wake/status":
            self._handle_status()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_wake(self):
        global _last_wake
        now = time.time()

        if now - _last_wake < 60:
            remaining = int(60 - (now - _last_wake))
            self._send_json(429, {
                "error": "rate limited",
                "retry_after_s": remaining,
                "message": f"Wake signal already sent. Try again in {remaining}s.",
            })
            return

        try:
            subprocess.run(
                ["wakeonlan", TARGET_MAC],
                capture_output=True, text=True, timeout=5,
            )
            _last_wake = now
            self._send_json(200, {
                "status": "wake_sent",
                "mac": TARGET_MAC,
                "message": "Wake-on-LAN packet sent. Server should boot in ~30-60 seconds.",
            })
        except FileNotFoundError:
            self._send_json(500, {"error": "wakeonlan not installed on gateway"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_status(self):
        """Check if .111 is reachable."""
        import socket
        try:
            sock = socket.create_connection((TARGET_IP, HEALTH_CHECK_PORT), timeout=3)
            sock.close()
            self._send_json(200, {"backend": "up", "host": TARGET_IP})
        except (ConnectionRefusedError, TimeoutError, OSError):
            self._send_json(200, {"backend": "down", "host": TARGET_IP})

    def _send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        # Quiet logging
        pass


if __name__ == "__main__":
    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), WakeHandler)
    print(f"Wake service listening on {LISTEN_HOST}:{LISTEN_PORT}")
    server.serve_forever()
