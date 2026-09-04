"""Exercise the canonical Caddy config against an offline upstream, without Docker."""

import copy
import http.client
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
OLD = (
    "sandbox allow-downloads allow-forms allow-modals allow-orientation-lock "
    "allow-pointer-lock allow-popups allow-popups-to-escape-sandbox "
    "allow-presentation allow-scripts allow-top-navigation-by-user-activation "
    "allow-top-navigation-to-custom-protocols"
)
NEW = OLD.replace(" allow-orientation-lock", "").replace(
    " allow-presentation", ""
).replace(" allow-scripts", " allow-scripts allow-same-origin")


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


class Upstream(http.server.BaseHTTPRequestHandler):
    policy = [OLD]
    seen = []

    def do_GET(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.seen.append((self.command, self.path, dict(self.headers), body))
        self.send_response(422 if self.command == "POST" else 200)
        for value in self.policy:
            self.send_header("Content-Security-Policy", value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Set-Cookie", "fixture=only; Path=/; Secure; HttpOnly; SameSite=Lax")
        self.send_header("Content-Length", "7")
        self.end_headers()
        self.wfile.write(b"fixture")

    do_POST = do_GET

    def log_message(self, *args):
        pass


class MyeventsCSP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="myevents-csp-")
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        env = dict(os.environ)
        # Read only the documented example, never the deployment secrets.
        for line in (ROOT / ".env.example").read_text().splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env[key] = value.strip('"')
        env["CADDY_LOG_DIR"] = str(folder)
        template = (ROOT / "config/Caddyfile.direct-combined-public").read_text()

        def adapt(source, name):
            snippet = folder / (name + ".caddy")
            snippet.write_text(source)
            caddyfile = folder / (name + ".Caddyfile")
            caddyfile.write_text(template.replace(
                "/etc/caddy/includes/direct.caddy", str(snippet)
            ))
            result = subprocess.run(
                ["caddy", "adapt", "--config", str(caddyfile)],
                env=env, capture_output=True, text=True, check=True,
            )
            return json.loads(result.stdout)

        cls.config = adapt((ROOT / "config/includes/direct.caddy").read_text(), "candidate")
        # The parent of the CSP-only commit remains the regression baseline.
        baseline = subprocess.check_output([
            "git", "show", "a0a53229a8c825732c03ffaa6683304ecd666d80:config/includes/direct.caddy"
        ], cwd=ROOT, text=True)
        cls.baseline = adapt(baseline, "baseline")
        candidate = folder / "candidate.Caddyfile"
        subprocess.run(["caddy", "validate", "--config", str(candidate)],
                       env=env, check=True, capture_output=True)

        cls.upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(cls.upstream.server_close)
        cls.addClassCleanup(cls.upstream.shutdown)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        # Keep actual adapted handlers; isolate listeners and replace ONLY the test transport.
        server = copy.deepcopy(next(s for s in cls.config["apps"]["http"]["servers"].values()
                                    if any("myevents.tonsurton.ch" in n.get("host", [])
                                           for n in walk(s))))
        server["listen"] = [f"127.0.0.1:{cls.port}"]
        server["automatic_https"] = {"disable": True}
        server.pop("tls_connection_policies", None)
        server.pop("logs", None)
        for node in walk(server):
            if node.get("handler") == "reverse_proxy":
                node["upstreams"] = [{"dial": f"127.0.0.1:{cls.upstream.server_port}"}]
                node["transport"] = {"protocol": "http", "versions": ["1.1"]}
        runtime = folder / "runtime.json"
        runtime.write_text(json.dumps({"admin": {"disabled": True},
            "apps": {"http": {"servers": {"fixture": server}}}}))
        cls.log = (folder / "caddy.log").open("w+")
        cls.addClassCleanup(cls.log.close)
        cls.process = subprocess.Popen(["caddy", "run", "--config", str(runtime)],
                                       stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop)
        for _ in range(100):
            if cls.process.poll() is not None:
                cls.log.seek(0)
                raise RuntimeError(cls.log.read())
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=.1):
                    break
            except OSError:
                time.sleep(.05)
        else:
            raise RuntimeError("Caddy fixture did not start")

    @classmethod
    def stop(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()

    def request(self, path="/", method="GET", host="myevents.tonsurton.ch", body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body, {"Host": host, "Cookie": "fixture=input",
                "Content-Type": "application/json", "X-Spirit-Edge-Key": "fixture-secret"})
            response = connection.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            connection.close()

    def test_policies_and_body(self):
        for policies, expected in [([OLD], [NEW]),
                (["default-src 'self'; " + OLD + "; frame-ancestors 'none'"],
                 ["default-src 'self'; " + NEW + "; frame-ancestors 'none'"]),
                ([OLD, "object-src 'none'"], [NEW, "object-src 'none'"]),
                ([NEW], [NEW]), ([], []),
                (["sandbox allow-scripts"], ["sandbox allow-scripts"]),
                ([OLD + " allow-storage-access-by-user-activation"],
                 [OLD + " allow-storage-access-by-user-activation"])]:
            with self.subTest(policies=policies):
                Upstream.policy = policies
                status, headers, body = self.request()
                self.assertEqual(status, 200)
                self.assertEqual([v for k, v in headers if k.lower() == "content-security-policy"], expected)
                self.assertEqual(body, b"fixture")
                self.assertIn(("Set-Cookie", "fixture=only; Path=/; Secure; HttpOnly; SameSite=Lax"), headers)
                self.assertFalse(any(k.lower().startswith("access-control-") for k, _ in headers))
        Upstream.policy = [OLD]

    def test_routes_methods_and_forwarding(self):
        Upstream.policy = [OLD]
        for path in ["/", "/register/", "/manage/test", "/admin", "/admin/login", "/theme.css"]:
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 200)
        payload = b'{"email":""}'
        status, headers, _ = self.request("/register/login/start?check=1", "POST", body=payload)
        self.assertEqual(status, 422)
        self.assertIn(("Content-Security-Policy", NEW), headers)
        method, path, forwarded, body = Upstream.seen[-1]
        self.assertEqual((method, path, body), ("POST", "/webhook/0key/tonsurton/events/register/login/start?check=1", payload))
        forwarded = {k.lower(): v for k, v in forwarded.items()}
        self.assertEqual(forwarded["host"], "n8n.monkey-eel.ts.net")
        self.assertEqual(forwarded["cookie"], "fixture=input")
        self.assertNotIn("x-spirit-edge-key", forwarded)
        self.assertEqual(forwarded["x-spirit-ingress"], "public-webhook-proxy")
        self.assertEqual(forwarded["x-spirit-client-ip"], "127.0.0.1")
        for path, method in [("/rest/", "GET"), ("/api/", "GET"), ("/signin", "GET"),
                ("/workflow/", "GET"), ("/unknown", "GET"),
                ("/webhook/0key/tonsurton/events/", "GET"),
                ("/register/login/start", "OPTIONS"), ("/admin", "PUT"), ("/theme.css", "POST")]:
            with self.subTest(path=path, method=method):
                count = len(Upstream.seen)
                self.assertEqual(self.request(path, method)[0], 404)
                self.assertEqual(len(Upstream.seen), count)
        _, headers, _ = self.request("/webhook/0key/tonsurton/events/", host="n8n-wh01.spiritviews.com")
        self.assertIn(("Content-Security-Policy", OLD), headers)

    def test_only_scoped_header_changes(self):
        def normalized(value):
            if isinstance(value, list):
                return [normalized(v) for v in value if not (
                    isinstance(v, dict) and "Content-Security-Policy" in
                    v.get("response", {}).get("replace", {}))]
            if isinstance(value, dict):
                return {k: normalized(v) for k, v in value.items() if k != "group"}
            return value
        self.assertEqual(normalized(self.config), normalized(self.baseline))
        replacements = [n for n in walk(self.config) if "Content-Security-Policy" in
                        n.get("response", {}).get("replace", {})]
        self.assertEqual(len(replacements), 1)
        self.assertTrue(replacements[0]["response"]["deferred"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
