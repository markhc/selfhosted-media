"""Controller-only enrollment tests against a loopback API, never a real tailnet."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
TEMP_ROOT = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None
TOKEN = "fake-controller-access-token"
KEY = "tskey-auth-fake-test-key-not-valid"
PRIVATE_ERROR = "fake-private-api-response-not-for-logs"


class EnrollmentTests(unittest.TestCase):
    def run_enrollment(self, status=200, valid_key=True):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append((self.path, body, self.headers.get("Authorization")))
                if self.path == "/api/v2/oauth/token":
                    code, response = 200, {"access_token": TOKEN}
                else:
                    code = status
                    response = ({"key": KEY if valid_key else "malformed-test-key"}
                                if status == 200 else {"message": PRIVATE_ERROR})
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="enrollment-test-", dir=TEMP_ROOT) as temp:
                play = [{
                    "name": "Test private enrollment against loopback only",
                    "hosts": "localhost", "gather_facts": False,
                    "vars": {
                        "nas_tailscale_directory": temp,
                        "nas_tailscale_api_url": f"http://127.0.0.1:{server.server_port}",
                        "nas_tailscale_auth_key_tags": ["tag:irc"],
                        "tailscale_oauth_client_id": "fake-client-id",
                        "tailscale_oauth_client_secret": "fake-oauth-secret",
                    },
                    "tasks": [{"name": "Test enrollment tasks only", "ansible.builtin.import_role": {
                        "name": "nas_tailscale", "tasks_from": "auth"}}],
                }]
                path = Path(temp) / "play.yml"
                path.write_text(yaml.safe_dump(play))
                result = subprocess.run(
                    [str(ROOT / ".venv/bin/ansible-playbook"), "-i", "localhost,", "-c", "local", "--diff", str(path)],
                    cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env={**os.environ, "ANSIBLE_NOCOLOR": "1"}, timeout=45,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        for secret in (TOKEN, KEY, PRIVATE_ERROR, "fake-oauth-secret"):
            self.assertNotIn(secret, result.stdout)
        return result, requests

    def test_policy_allows_each_tag_as_a_subset_without_cross_ownership(self):
        policy = (ROOT / "tailscale/policy.hujson").read_text()
        policy = re.sub(r"//[^\n]*", "", policy)
        policy = json.loads(re.sub(r",\s*([}\]])", r"\1", policy))
        for tag in ("tag:nas", "tag:irc"):
            self.assertEqual(set(policy["tagOwners"][tag]), {"autogroup:admin", tag})

    def test_single_tag_key_is_short_lived_and_not_reusable(self):
        result, requests = self.run_enrollment()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(requests), 2)
        path, raw_body, authorization = requests[1]
        self.assertEqual(path, "/api/v2/tailnet/-/keys")
        self.assertEqual(authorization, "Bearer " + TOKEN)
        body = json.loads(raw_body)
        self.assertEqual(body["expirySeconds"], 600)
        self.assertEqual(body["capabilities"]["devices"]["create"], {
            "reusable": False, "ephemeral": False, "preauthorized": True, "tags": ["tag:irc"],
        })

    def test_rejected_key_reports_status_and_tag_guidance_not_api_body(self):
        result, _ = self.run_enrollment(status=403)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP 403", result.stdout)
        self.assertIn("explicit tag ownership", result.stdout)

    def test_http_success_without_valid_key_still_fails_closed(self):
        result, _ = self.run_enrollment(valid_key=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HTTP 200", result.stdout)


if __name__ == "__main__":
    unittest.main()
