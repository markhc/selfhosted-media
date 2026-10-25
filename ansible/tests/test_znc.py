"""Offline role checks; opt in to the isolated Docker smoke test with ZNC_CONTAINER_TESTS=1."""

import base64
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unittest
import uuid

import yaml
from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[2]
ANSIBLE = ROOT / ".venv/bin/ansible-playbook"
ROLE = ROOT / "ansible/roles/znc"
TEMP_ROOT = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None
# Generated with znc --makepass for the deliberately fake test password below.
TEST_HASH = (
    "$argon2id$v=19$m=6144,t=6,p=1$KipPR0k4KDREdClEOmFXUTBGcUw$"
    "WLSA7BGqXhE7f7iYuOzU4P/8uQ9FwkDeT2yYYTpKkHI"
)
SECRETS = ["fake-buffer-secret-for-tests", "fake-server-password", "fake-sasl %;&' password"]


def instance():
    return {
        "savebuff_password": SECRETS[0],
        "users": [{
            "name": "exampleuser",
            "nick": "ExampleNick",
            "password_hash": TEST_HASH,
            "networks": [{
                "name": "example_network",
                "servers": [{"host": "irc.example.net", "password": SECRETS[1]}],
                "sasl": {"username": "exampleaccount", "password": SECRETS[2]},
                "channels": [{"name": "#example-channel", "key": "fake-channel-key"}],
            }],
        }],
    }


def run_role(directory, config=None, render=False, extra=None):
    variables = {
        "ansible_facts": {"distribution": "Debian"},
        "znc_instances": {"znc_vm": config if config is not None else instance()},
        "znc_tailscale_ip": {"stdout": "100.100.100.100\n"},
    }
    variables.update(extra or {})
    tasks = [{"name": "Validate fixture", "ansible.builtin.import_role": {
        "name": "znc", "tasks_from": "validate"}}]
    if render:
        sources = ["compose.yml", "znc.conf", "start.sh", "generate-tls.sh"]
        if variables.get("znc_tls_mode") == "cloudflare":
            sources += ["install-acme.sh", "renew-acme.sh",
                        "selfhosted-znc-acme.service", "selfhosted-znc-acme.timer"]
        for source in sources:
            tasks.append({
                "name": "Render confidential fixture",
                "ansible.builtin.template": {
                    "src": str(ROLE / "templates" / (source + ".j2")),
                    "dest": str(directory / source),
                    "mode": "0600",
                },
                "no_log": True,
                "diff": False,
            })
    play = [{"name": "Check ZNC fixtures", "hosts": "all", "gather_facts": False,
             "vars": variables, "tasks": tasks}]
    path = directory / "play.yml"
    path.write_text(yaml.safe_dump(play))
    return subprocess.run(
        [str(ANSIBLE), "-i", "znc_vm,", "-c", "local", "--diff", str(path)],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**os.environ, "ANSIBLE_NOCOLOR": "1"}, timeout=60,
    )


class ZncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="znc-test-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        cls.result = run_role(cls.directory, render=True)
        if cls.result.returncode:
            raise AssertionError(cls.result.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_compose_project_name_matches_deployment(self):
        compose = yaml.safe_load((self.directory / "compose.yml").read_text())
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        deployment = next(task["community.docker.docker_compose_v2"] for task in tasks
                          if "community.docker.docker_compose_v2" in task)
        self.assertEqual(compose["name"], "selfhosted-znc")
        self.assertEqual(compose["name"], deployment["project_name"])

    def test_private_small_container(self):
        service = yaml.safe_load((self.directory / "compose.yml").read_text())["services"]["znc"]
        self.assertEqual(service["image"], "znc:1.10.3-slim")
        self.assertEqual(service["network_mode"], "host")
        self.assertNotIn("ports", service)
        self.assertNotIn("environment", service)
        self.assertEqual(service["user"], "10000:10000")
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertTrue(service["read_only"])
        self.assertEqual(service["mem_limit"], "128m")
        self.assertIn("./managed:/znc-managed:ro", service["volumes"])
        self.assertIn("./tls:/znc-tls:ro", service["volumes"])
        self.assertIn("openssl s_client", service["healthcheck"]["test"][1])
        self.assertIn("-verify_return_error", service["healthcheck"]["test"][1])
        for secret in SECRETS:
            self.assertNotIn(secret, (self.directory / "compose.yml").read_text())

    def test_managed_config_and_bounded_durable_buffers(self):
        config = (self.directory / "znc.conf").read_text()
        self.assertEqual(config.count("<Listener "), 1)
        self.assertIn("Host = 100.100.100.100", config)
        self.assertIn("IPv6 = false", config)
        self.assertIn("SSL = true", config)
        self.assertIn("SSLCertFile = /znc-tls/server.crt", config)
        self.assertIn("SSLKeyFile = /znc-tls/server.key", config)
        self.assertIn("AllowWeb = false", config)
        self.assertIn("Admin = false", config)
        self.assertIn("Server = irc.example.net +6697 fake-server-password\n", config)
        self.assertIn("TrustAllCerts = false", config)
        self.assertIn("AutoClearChanBuffer = false", config)
        self.assertIn("AutoClearQueryBuffer = false", config)
        self.assertIn("ChanBufferSize = 1000", config)
        self.assertIn("MaxQueryBuffers = 50", config)
        self.assertIn("LoadModule = savebuff " + SECRETS[0], config)
        script = (self.directory / "start.sh").read_text()
        self.assertIn("cp /znc-managed/znc.conf /znc-data/configs/znc.conf", script)
        self.assertIn("exec /opt/znc/bin/znc --foreground", script)
        self.assertEqual(subprocess.run(["sh", "-n", str(self.directory / "start.sh")]).returncode, 0)

    def test_tls_generation_is_private_and_renewable(self):
        script = (self.directory / "generate-tls.sh").read_text()
        self.assertIn("umask 077", script)
        self.assertIn("subjectAltName=IP:100.100.100.100", script)
        self.assertIn("-checkend 2592000", script)
        self.assertIn("-days 365", script)
        self.assertIn("if [ ! -e \"$key\" ]", script)
        self.assertEqual(subprocess.run(["sh", "-n", str(self.directory / "generate-tls.sh")]).returncode, 0)

    def test_invalid_tls_settings_fail(self):
        for extra in ({"znc_tls_hostname": "znc.example.net';bad"},
                      {"znc_tls_certificate_days": 30, "znc_tls_renew_before_days": 30},
                      {"znc_tls_renew_before_days": 0}):
            with self.subTest(extra=extra):
                result = run_role(self.directory, extra=extra)
                self.assertNotEqual(result.returncode, 0)

    def test_sasl_registry_encoding_round_trips(self):
        script = (self.directory / "start.sh").read_text()
        encoded = re.search(r"^password (.*)$", script, re.MULTILINE)[1]
        decoded = re.sub(r"%([a-fA-F0-9]{2});", lambda m: chr(int(m[1], 16)), encoded)
        self.assertEqual(decoded, SECRETS[2])
        self.assertNotRegex(encoded, r"\s")
        self.assertIn("require_auth true", script)

    def test_diff_output_is_redacted(self):
        for secret in [*SECRETS, TEST_HASH, "fake-channel-key"]:
            self.assertNotIn(secret, self.result.stdout)
        for name in ("znc.conf", "start.sh"):
            self.assertEqual((self.directory / name).stat().st_mode & 0o777, 0o600)

    def test_rendering_is_idempotent(self):
        result = run_role(self.directory, render=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout, r"changed=0\s")

    def test_invalid_credentials_and_config_injection_fail_redacted(self):
        cases = []
        bad = instance()
        bad["users"] = []
        cases.append(bad)
        bad = instance()
        bad["savebuff_password"] = "short"
        cases.append(bad)
        bad = instance()
        bad["users"][0]["password_hash"] = "plaintext-password-is-not-a-hash"
        cases.append(bad)
        bad = instance()
        bad["users"][0]["networks"][0]["name"] = "../../other-host"
        cases.append(bad)
        bad = instance()
        bad["users"][0]["networks"][0]["servers"][0]["password"] = "fake-server-password\n<Listener public>"
        cases.append(bad)
        bad = instance()
        bad["users"][0]["networks"][0]["channels"][0]["name"] = "#example>\n</User>"
        cases.append(bad)
        for index, config in enumerate(cases):
            with self.subTest(config_index=index):
                result = run_role(self.directory, config)
                self.assertNotEqual(result.returncode, 0)
                for secret in SECRETS:
                    self.assertNotIn(secret, result.stdout)

    def test_vault_instance_is_selected_by_inventory_host(self):
        result = run_role(self.directory, extra={"znc_instances": {"another_host": instance()}})
        self.assertNotEqual(result.returncode, 0)

    def test_optional_sasl_and_channels(self):
        config = instance()
        del config["users"][0]["networks"][0]["sasl"]
        del config["users"][0]["networks"][0]["channels"]
        result = run_role(self.directory, config)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_service_selection_and_host_separation(self):
        play = yaml.safe_load((ROOT / "ansible/playbooks/site.yml").read_text())[0]
        env = Environment()
        env.filters['bool'] = FilterModule().filters()['bool']
        roles = {role["role"]: role for role in play["roles"]}
        selected = env.compile_expression(roles["znc"]["when"])
        self.assertFalse(selected())
        self.assertFalse(selected(selfhosted_services={"znc": {"enabled": False}}))
        self.assertTrue(selected(selfhosted_services={"znc": {"enabled": True}}))
        web = env.compile_expression(roles["web_stack"]["when"])
        self.assertFalse(web(group_names=["irc_bouncers"], selfhosted_services={"caddy": {"enabled": True}}))
        for group in ("nas", "irc_bouncers"):
            settings = yaml.safe_load((ROOT / f"ansible/inventories/example/group_vars/{group}.yml").read_text())
            self.assertFalse(settings["selfhosted_services"]["znc"]["enabled"])
        runtime = env.compile_expression(roles["docker_runtime"]["when"])
        self.assertFalse(runtime(group_names=["nas"], ansible_run_tags=["znc"],
                                 selfhosted_services={"caddy": {"enabled": True}}))
        self.assertTrue(runtime(group_names=["irc_bouncers"], ansible_run_tags=["znc"],
                                selfhosted_services={"znc": {"enabled": True}}))

    @unittest.skipUnless(os.environ.get("ZNC_CONTAINER_TESTS") == "1", "opt-in Docker smoke test")
    def test_container_start_authenticate_restart_and_savebuff(self):
        # No published ports, host network, upstream connectivity, or real credentials.
        # Use loopback only *inside* an isolated container, not a production binding.
        with tempfile.TemporaryDirectory(prefix="znc-container-", dir=TEMP_ROOT) as temp:
            base = Path(temp)
            managed = base / "managed"
            managed.mkdir()
            (base / "data").mkdir()
            tls = base / "tls"
            tls.mkdir()
            config = instance()
            config["users"][0]["networks"][0]["servers"][0]["port"] = 16697
            result = run_role(managed, config, render=True, extra={
                "znc_tailscale_ip": {"stdout": "127.0.0.1"}, "znc_tls_hostname": "znc.example.net"})
            self.assertEqual(result.returncode, 0, result.stdout)
            name = "selfhosted-znc-test-" + uuid.uuid4().hex[:12]

            def docker(*args, **kwargs):
                return subprocess.run(["docker", *args], text=True, capture_output=True, timeout=45, **kwargs)

            def client(command):
                # Explicitly trust the generated self-signed certificate and verify its IP.
                lines = ("PASS exampleuser/example_network:example-test-password\r\n"
                         "NICK ExampleNick\r\nUSER exampleuser 0 * :Test\r\n" + command)
                result = docker("exec", "-i", name, "timeout", "2", "openssl", "s_client",
                                "-connect", "127.0.0.1:6697", "-CAfile", "/znc-tls/server.crt",
                                "-verify_return_error", "-verify_ip", "127.0.0.1", "-quiet", input=lines)
                # GNU timeout returns 124; the image's BusyBox timeout returns 143.
                self.assertIn(result.returncode, (0, 124, 143), result.stderr)
                return result.stdout

            def wait_ready():
                healthcheck = yaml.safe_load((managed / "compose.yml").read_text())["services"]["znc"]["healthcheck"]["test"][1]
                ready = docker("exec", name, "sh", "-c",
                               f"for i in 1 2 3 4 5; do {healthcheck} && exit 0; sleep 1; done; exit 1")
                self.assertEqual(ready.returncode, 0, docker("logs", name).stdout)

            def generate_tls():
                return docker(
                    "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
                    "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                    "--mount", f"type=bind,src={managed / 'generate-tls.sh'},dst=/generate-tls.sh,readonly",
                    "--mount", f"type=bind,src={tls},dst=/znc-tls", "--entrypoint", "/bin/sh",
                    "znc:1.10.3-slim", "/generate-tls.sh",
                )

            upstream = None
            upstream_ready = threading.Event()
            authenticated = []
            write_lock = threading.Lock()

            def server_send(line):
                with write_lock:
                    upstream.stdin.write(line + "\r\n")
                    upstream.stdin.flush()

            def serve_irc():
                for line in upstream.stdout:
                    line = line.strip()
                    if line.startswith("CAP LS"):
                        server_send(":irc.example.net CAP * LS :sasl")
                    elif line.startswith("CAP REQ"):
                        server_send(":irc.example.net CAP * ACK :sasl")
                    elif line == "AUTHENTICATE PLAIN":
                        server_send("AUTHENTICATE +")
                    elif line.startswith("AUTHENTICATE "):
                        authenticated.append(base64.b64decode(line.split()[1]).decode())
                        server_send(":irc.example.net 903 ExampleNick :SASL authentication successful")
                    elif line == "CAP END":
                        server_send(":irc.example.net 001 ExampleNick :Welcome to the fake IRC network")
                        upstream_ready.set()
                    elif line.startswith("PING "):
                        server_send("PONG " + line[5:])

            try:
                result = generate_tls()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("ZNC_TLS_CHANGED", result.stdout)
                key = (tls / "server.key").read_bytes()
                certificate = (tls / "server.crt").read_bytes()
                self.assertEqual((tls / "server.key").stat().st_mode & 0o777, 0o600)
                self.assertEqual((tls / "server.crt").stat().st_mode & 0o777, 0o600)
                result = generate_tls()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("ZNC_TLS_CHANGED", result.stdout)
                self.assertEqual((tls / "server.crt").read_bytes(), certificate)
                # Replace only the test certificate with one inside the renewal window.
                result = docker(
                    "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
                    "--mount", f"type=bind,src={tls},dst=/znc-tls", "--entrypoint", "openssl",
                    "znc:1.10.3-slim", "req", "-new", "-x509", "-key", "/znc-tls/server.key",
                    "-out", "/znc-tls/server.crt", "-days", "1", "-subj", "/CN=znc.example.net",
                    "-addext", "subjectAltName=IP:127.0.0.1,DNS:znc.example.net",
                    "-addext", "extendedKeyUsage=serverAuth",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                expiring = (tls / "server.crt").read_bytes()
                result = generate_tls()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("ZNC_TLS_CHANGED", result.stdout)
                self.assertNotEqual((tls / "server.crt").read_bytes(), expiring)
                self.assertEqual((tls / "server.key").read_bytes(), key)
                certificate = (tls / "server.crt").read_bytes()
                result = docker(
                    "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
                    "--mount", f"type=bind,src={managed},dst=/fixtures", "--entrypoint", "openssl",
                    "znc:1.10.3-slim", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", "/fixtures/test.key", "-out", "/fixtures/test.crt", "-days", "1",
                    "-subj", "/CN=irc.example.net", "-addext", "subjectAltName=DNS:irc.example.net",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                result = docker(
                    "run", "--detach", "--name", name, "--network", "none",
                    "--user", f"{os.getuid()}:{os.getgid()}", "--read-only", "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges:true", "--memory", "128m",
                    "--add-host", "irc.example.net:127.0.0.1", "--env", "SSL_CERT_FILE=/znc-managed/test.crt",
                    "--mount", f"type=bind,src={managed},dst=/znc-managed,readonly",
                    "--mount", f"type=bind,src={base / 'data'},dst=/znc-data",
                    "--mount", f"type=bind,src={tls},dst=/znc-tls,readonly",
                    "--entrypoint", "/bin/sh", "znc:1.10.3-slim", "/znc-managed/start.sh",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                upstream = subprocess.Popen(
                    ["docker", "exec", "-i", name, "openssl", "s_server", "-quiet", "-naccept", "1",
                     "-accept", "127.0.0.1:16697", "-cert", "/znc-managed/test.crt", "-key", "/znc-managed/test.key"],
                    text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    bufsize=1,
                )
                responder = threading.Thread(target=serve_irc, daemon=True)
                responder.start()
                wait_ready()
                # A different DNS identity must fail validation, not silently bypass TLS.
                result = docker("exec", name, "openssl", "s_client", "-connect", "127.0.0.1:6697",
                                "-CAfile", "/znc-tls/server.crt", "-verify_return_error",
                                "-verify_hostname", "wrong.example.net", "-brief", "-no_ign_eof")
                self.assertNotEqual(result.returncode, 0)
                result = docker("exec", name, "openssl", "s_client", "-connect", "127.0.0.1:6697",
                                "-CAfile", "/znc-tls/server.crt", "-verify_return_error",
                                "-verify_hostname", "znc.example.net", "-brief", "-no_ign_eof")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(upstream_ready.wait(timeout=20), docker("logs", name).stdout)
                self.assertEqual(authenticated, ["exampleaccount\0exampleaccount\0" + SECRETS[2]])
                # Disconnect the client, deliver an upstream private message, then reconnect.
                self.assertIn(" 001 ", client(""))
                server_send(":sender!sender@example.invalid PRIVMSG ExampleNick :OFFLINE_MESSAGE_MARKER")
                output = client("PRIVMSG *savebuff :save\r\n")
                self.assertIn(" 001 ", output)
                self.assertIn("Done.", output)
                self.assertIn("OFFLINE_MESSAGE_MARKER", output)
                buffers = list((base / "data/users/exampleuser/networks/example_network/moddata/savebuff").iterdir())
                self.assertTrue(buffers)
                self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in buffers))
                self.assertTrue(all(b"OFFLINE_MESSAGE_MARKER" not in path.read_bytes() for path in buffers))
                source = (managed / "znc.conf").read_bytes()
                result = docker("restart", name)
                self.assertEqual(result.returncode, 0, result.stderr)
                wait_ready()
                self.assertIn("OFFLINE_MESSAGE_MARKER", client("PRIVMSG *savebuff :save\r\n"))
                self.assertEqual((managed / "znc.conf").read_bytes(), source)
                self.assertEqual((tls / "server.crt").read_bytes(), certificate)
                self.assertEqual((tls / "server.key").read_bytes(), key)
                self.assertNotIn("Failed to Decrypt", docker("logs", name).stdout)
            finally:
                docker("rm", "--force", name)
                if upstream is not None:
                    upstream.terminate()
                    upstream.wait(timeout=10)
                    upstream.stdin.close()
                    upstream.stdout.close()


if __name__ == "__main__":
    unittest.main()
