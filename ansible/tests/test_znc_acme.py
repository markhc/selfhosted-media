"""Cloudflare TLS rendering and renewal/install failure paths; no real API calls."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

import yaml

from test_znc import ROLE, TEMP_ROOT, instance, run_role


TOKEN = "FAKE_CLOUDFLARE_TOKEN_FOR_OFFLINE_TESTS"
SETTINGS = {
    "znc_tls_mode": "cloudflare",
    "znc_tls_hostname": "irc.example.com",
    "znc_acme_email": "operator@example.com",
}


def acme_instance():
    config = instance()
    config["cloudflare_api_token"] = TOKEN
    return config


class AcmeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="znc-acme-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        cls.result = run_role(cls.directory, acme_instance(), render=True, extra={
            **SETTINGS, "znc_directory": str(cls.directory),
        })
        if cls.result.returncode:
            raise AssertionError(cls.result.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_public_certificate_and_private_listener(self):
        config = (self.directory / "znc.conf").read_text()
        self.assertIn("SSLCertFile = /znc-tls/acme.pem", config)
        self.assertIn("SSLKeyFile = /znc-tls/acme.pem", config)
        self.assertIn("Host = 100.100.100.100", config)
        service = yaml.safe_load((self.directory / "compose.yml").read_text())["services"]["znc"]
        self.assertEqual(service["network_mode"], "host")
        self.assertNotIn("ports", service)
        self.assertEqual(service["environment"], {"TZ": "UTC"})
        self.assertNotIn("acme/", str(service["volumes"]))
        check = service["healthcheck"]["test"][1]
        self.assertIn("-verify_hostname irc.example.com", check)
        self.assertIn("-servername irc.example.com", check)
        self.assertIn("-verify_return_error", check)
        self.assertNotIn("-CAfile", check)
        self.assertNotIn("-verify_ip", check)

    def test_renewal_is_scoped_serialized_and_secret_free(self):
        script = (self.directory / "renew-acme.sh").read_text()
        self.assertIn("flock -w 900 9", script)
        self.assertIn("--keep-until-expiring --renew-with-new-domains", script)
        self.assertIn("--dns-cloudflare-credentials /cloudflare.ini", script)
        self.assertIn("certbot/dns-cloudflare:v5.8.0", script)
        self.assertIn("--log-driver none", script)
        self.assertIn("--network none", script)
        self.assertNotIn("--network host", script)
        self.assertNotIn("docker.sock", script)
        self.assertNotIn("--publish", script)
        for name in ("renew-acme.sh", "install-acme.sh"):
            self.assertEqual(subprocess.run(["sh", "-n", str(self.directory / name)]).returncode, 0)
        for path in self.directory.iterdir():
            if path.name != "play.yml":  # The private, temporary Ansible fixture contains fake inputs.
                self.assertNotIn(TOKEN, path.read_text())
        self.assertNotIn(TOKEN, self.result.stdout)

    def test_persistent_timer_and_explicit_mode_gates(self):
        timer = (self.directory / "selfhosted-znc-acme.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 00,12:00:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("RandomizedDelaySec=1h", timer)
        service = (self.directory / "selfhosted-znc-acme.service").read_text()
        self.assertIn("ConditionPathExists=", service)
        self.assertIn("StandardOutput=null", service)
        tasks = yaml.safe_load((ROLE / "tasks/tls.yml").read_text())
        cloudflare = next(t for t in tasks if t.get("ansible.builtin.include_tasks") == "tls-cloudflare.yml")
        self.assertEqual(cloudflare["when"], "znc_tls_mode == 'cloudflare'")
        stop = next(t for t in tasks if "ansible.builtin.systemd_service" in t)
        self.assertIn("self_signed", stop["when"])
        self.assertEqual(stop["ansible.builtin.systemd_service"]["state"], "stopped")
        self.assertFalse(stop["ansible.builtin.systemd_service"]["enabled"])
        credential = next(t for t in yaml.safe_load((ROLE / "tasks/tls-cloudflare.yml").read_text())
                          if "ansible.builtin.copy" in t)
        self.assertTrue(credential["no_log"])
        self.assertFalse(credential["diff"])
        self.assertEqual(credential["ansible.builtin.copy"]["mode"], "0600")

    def test_missing_and_invalid_inputs_fail_without_leaking_token(self):
        for extra in ({"znc_tls_mode": "invalid"}, {"znc_tls_hostname": ""},
                      {"znc_acme_email": ""}, {"znc_acme_email": "bad\nemail@example.com"},
                      {"znc_acme_dns_propagation_seconds": 0},
                      {"znc_cloudflare_api_token": "bad\nTOKEN"},
                      {"znc_cloudflare_api_token": ""}):
            with self.subTest(extra=extra):
                result = run_role(self.directory, acme_instance(), extra={**SETTINGS, **extra})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(TOKEN, result.stdout)
        # Caddy's token must not implicitly authorize the bouncer.
        result = run_role(self.directory, instance(), extra={
            **SETTINGS, "caddy_cloudflare_api_token": TOKEN,
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(TOKEN, result.stdout)


class RenewalScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="znc-renew-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role(cls.directory, acme_instance(), render=True, extra={
            **SETTINGS, "znc_directory": str(cls.directory),
        })
        if result.returncode:
            raise AssertionError(result.stdout)
        (cls.directory / "acme").mkdir()
        (cls.directory / "tls").mkdir()
        (cls.directory / "bin").mkdir()
        docker = cls.directory / "bin/docker"
        docker.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(args) + "\\n")
if args[0] == "run":
    if "certonly" in args:
        if os.environ.get("FAKE_ISSUE_FAIL"):
            print("FAKE_SECRET_DIAGNOSTIC", file=sys.stderr)
            sys.exit(17)
    else:
        if os.environ.get("FAKE_INSTALL_FAIL"):
            print("FAKE_SECRET_DIAGNOSTIC", file=sys.stderr)
            sys.exit(18)
        if os.environ.get("FAKE_CHANGE"):
            print("ZNC_TLS_CHANGED")
elif "ps" in args:
    if not os.environ.get("FAKE_STOPPED"):
        print("fake-container-id")
elif "restart" in args and os.environ.get("FAKE_RESTART_FAIL"):
    print("FAKE_SECRET_DIAGNOSTIC", file=sys.stderr)
    sys.exit(19)
''')
        docker.chmod(0o700)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.calls = self.directory / "calls.jsonl"
        self.calls.write_text("")
        self.marker = self.directory / "tls/acme-restart-required"
        self.marker.unlink(missing_ok=True)

    def run_script(self, *args, **variables):
        return subprocess.run(
            ["sh", str(self.directory / "renew-acme.sh"), *args],
            env={**os.environ, "PATH": str(self.directory / "bin") + os.pathsep + os.environ["PATH"],
                 "FAKE_CALLS": str(self.calls), **variables},
            text=True, capture_output=True, timeout=15,
        )

    def restarts(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines() if '"restart"' in line]

    def test_unchanged_does_not_restart(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.restarts())

    def test_change_restarts_only_running_service(self):
        result = self.run_script(FAKE_CHANGE="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.restarts()), 1)
        self.assertFalse(self.marker.exists())
        result = self.run_script(FAKE_CHANGE="1", FAKE_STOPPED="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.restarts()), 1)
        self.assertTrue(self.marker.exists())

    def test_deployment_defers_restart_and_remembers_pending_change(self):
        result = self.run_script("--no-restart", FAKE_CHANGE="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ZNC_TLS_CHANGED", result.stdout)
        self.assertTrue(self.marker.exists())
        self.assertFalse(self.restarts())
        result = self.run_script("--no-restart")
        self.assertIn("ZNC_TLS_CHANGED", result.stdout)
        self.assertTrue(self.marker.exists())

    def test_failed_restart_is_retried_without_another_renewal(self):
        result = self.run_script(FAKE_CHANGE="1", FAKE_RESTART_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("FAKE_SECRET_DIAGNOSTIC", result.stdout + result.stderr)
        self.assertTrue(self.marker.exists())
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.restarts()), 2)
        self.assertFalse(self.marker.exists())

    def test_issuance_and_validation_failures_do_not_restart_or_leak(self):
        for failure in ("FAKE_ISSUE_FAIL", "FAKE_INSTALL_FAIL"):
            with self.subTest(failure=failure):
                result = self.run_script(**{failure: "1"})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("FAKE_SECRET_DIAGNOSTIC", result.stdout + result.stderr)
                self.assertFalse(self.restarts())
                self.assertFalse(self.marker.exists())


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for offline certificate tests")
class CertificateInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="znc-cert-", dir=TEMP_ROOT)
        cls.directory = Path(cls.temp.name)
        result = run_role(cls.directory, acme_instance(), render=True, extra=SETTINGS)
        if result.returncode:
            raise AssertionError(result.stdout)
        cls.openssl("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                    "-nodes", "-keyout", str(cls.directory / "ca.key"),
                    "-out", str(cls.directory / "ca.crt"), "-days", "3", "-subj", "/CN=Example Test Root",
                    "-addext", "basicConstraints=critical,CA:TRUE",
                    "-addext", "keyUsage=critical,keyCertSign,cRLSign")

    @classmethod
    def openssl(cls, *args):
        result = subprocess.run(["openssl", *args], text=True, capture_output=True, timeout=15)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory(prefix="fixture-", dir=self.directory)
        self.addCleanup(self.fixture.cleanup)
        self.base = Path(self.fixture.name)
        self.lineage = self.base / "acme/live/znc"
        self.lineage.mkdir(parents=True)
        (self.base / "tls").mkdir()
        self.target = self.base / "tls/acme.pem"
        self.target.write_text("previous-certificate-and-key")
        source = (self.directory / "install-acme.sh").read_text()
        self.script = self.base / "install.sh"
        self.script.write_text(source.replace("/acme/live/znc", str(self.lineage))
                               .replace("/znc-tls", str(self.base / "tls")))
        self.issue()

    def issue(self, hostname="irc.example.com", days="2"):
        self.openssl("req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                     "-nodes", "-keyout", str(self.lineage / "privkey.pem"),
                     "-out", str(self.base / "request.csr"), "-subj", "/CN=" + hostname)
        extensions = self.base / "extensions.cnf"
        extensions.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
                              "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:" + hostname + "\n")
        self.openssl("x509", "-req", "-in", str(self.base / "request.csr"),
                     "-CA", str(self.directory / "ca.crt"), "-CAkey", str(self.directory / "ca.key"),
                     "-set_serial", "42", "-days", days, "-extfile", str(extensions),
                     "-out", str(self.lineage / "cert.pem"))
        (self.lineage / "fullchain.pem").write_bytes(
            (self.lineage / "cert.pem").read_bytes() + (self.directory / "ca.crt").read_bytes())

    def install(self, trusted=True):
        return subprocess.run(
            ["sh", str(self.script)], text=True, capture_output=True, timeout=15,
            env={**os.environ, "SSL_CERT_FILE": str(self.directory / "ca.crt") if trusted else "/dev/null",
                 "SSL_CERT_DIR": str(self.base / "empty-ca-directory")},
        )

    def assert_preserved(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target.read_text(), "previous-certificate-and-key")
        self.assertFalse(self.target.with_suffix(".pem.new").exists())

    def test_install_chain_key_permissions_and_unchanged_certificate(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ZNC_TLS_CHANGED", result.stdout)
        self.assertEqual(self.target.read_bytes(), (self.lineage / "privkey.pem").read_bytes()
                         + (self.lineage / "fullchain.pem").read_bytes())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.base / "tls/acme-restart-required").exists())
        before = self.target.stat().st_mtime_ns
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.target.stat().st_mtime_ns, before)
        # Certbot rotates keys by default. Install the new pair together.
        self.issue()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ZNC_TLS_CHANGED", result.stdout)

    def test_untrusted_chain_preserves_existing_certificate(self):
        self.assert_preserved(self.install(trusted=False))

    def test_wrong_hostname_preserves_existing_certificate(self):
        self.issue(hostname="other.example.com")
        self.assert_preserved(self.install())

    def test_expired_certificate_preserves_existing_certificate(self):
        self.issue(days="0")
        self.assert_preserved(self.install())

    def test_mismatched_key_preserves_existing_certificate(self):
        shutil.copyfile(self.directory / "ca.key", self.lineage / "privkey.pem")
        self.assert_preserved(self.install())

    def test_malformed_chain_preserves_existing_certificate(self):
        (self.lineage / "fullchain.pem").write_text("not-a-certificate")
        self.assert_preserved(self.install())

    @unittest.skipUnless(os.environ.get("ZNC_CONTAINER_TESTS") == "1", "opt-in Docker smoke test")
    def test_container_uses_acme_pem_and_verifies_hostname(self):
        self.assertEqual(self.install().returncode, 0)
        managed = self.base / "managed"
        managed.mkdir()
        data = self.base / "data"
        data.mkdir()
        result = run_role(managed, acme_instance(), render=True, extra={
            **SETTINGS, "znc_tailscale_ip": {"stdout": "127.0.0.1"},
        })
        self.assertEqual(result.returncode, 0, result.stdout)
        name = "selfhosted-znc-acme-test-" + uuid.uuid4().hex[:12]

        def docker(*args):
            return subprocess.run(["docker", *args], text=True, capture_output=True, timeout=45)

        try:
            result = docker(
                "run", "--detach", "--name", name, "--network", "none",
                "--user", f"{os.getuid()}:{os.getgid()}", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--memory", "128m",
                "--env", "SSL_CERT_FILE=/test-ca.crt",
                "--mount", f"type=bind,src={managed},dst=/znc-managed,readonly",
                "--mount", f"type=bind,src={data},dst=/znc-data",
                "--mount", f"type=bind,src={self.base / 'tls'},dst=/znc-tls,readonly",
                "--mount", f"type=bind,src={self.directory / 'ca.crt'},dst=/test-ca.crt,readonly",
                "--entrypoint", "/bin/sh", "znc:1.10.3-slim", "/znc-managed/start.sh",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            healthcheck = yaml.safe_load((managed / "compose.yml").read_text())["services"]["znc"]["healthcheck"]["test"][1]
            ready = docker("exec", name, "sh", "-c",
                           f"for i in 1 2 3 4 5; do {healthcheck} && exit 0; sleep 1; done; exit 1")
            self.assertEqual(ready.returncode, 0, docker("logs", name).stdout)
            result = docker("exec", name, "openssl", "s_client", "-connect", "127.0.0.1:6697",
                            "-verify_return_error", "-verify_hostname", "wrong.example.com",
                            "-brief", "-no_ign_eof")
            self.assertNotEqual(result.returncode, 0)
        finally:
            docker("rm", "--force", name)

    @unittest.skipUnless(os.environ.get("ZNC_CONTAINER_TESTS") == "1", "opt-in Docker smoke test")
    def test_certbot_plugin_runs_with_hardened_non_root_runtime(self):
        arguments = ["docker", "run", "--rm", "--network", "none", "--log-driver", "none",
                     "--user", f"{os.getuid()}:{os.getgid()}", "--read-only", "--cap-drop", "ALL",
                     "--security-opt", "no-new-privileges:true", "--memory", "256m", "--pids-limit", "64",
                     "--tmpfs", "/tmp:size=32m,mode=1777"]
        for name, target in (("config", "/etc/letsencrypt"), ("work", "/var/lib/letsencrypt"),
                             ("logs", "/var/log/letsencrypt")):
            path = self.base / name
            path.mkdir(mode=0o700)
            arguments += ["--mount", f"type=bind,src={path},dst={target}"]
        arguments += ["certbot/dns-cloudflare:v5.8.0", "plugins", "--non-interactive"]
        result = subprocess.run(arguments, text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dns-cloudflare", result.stdout)


if __name__ == "__main__":
    unittest.main()
