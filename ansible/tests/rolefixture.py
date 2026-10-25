"""Run a role's validation and render its templates offline with ansible-playbook."""

import os
from pathlib import Path
import re
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
ANSIBLE = ROOT / ".venv/bin/ansible-playbook"
TEMP_ROOT = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None
FACTS = {"distribution": "Debian"}


def playbook(directory, inventory, variables, tasks, forks=5, env=None):
    """Run TASKS with play VARIABLES on every local fake host in INVENTORY."""
    play = [{"name": "Check fixtures", "hosts": "all", "gather_facts": False,
             "vars": {"ansible_facts": FACTS, **variables}, "tasks": tasks}]
    path = Path(directory) / "play.yml"
    path.write_text(yaml.safe_dump(play))
    return subprocess.run(
        [str(ANSIBLE), "-i", inventory, "-c", "local", "-f", str(forks), "--diff", str(path)],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**os.environ, "ANSIBLE_NOCOLOR": "1", **(env or {})}, timeout=120,
    )


def run_play(directory, variables, tasks, host="nas_server"):
    """Run TASKS against a local fake HOST with Debian facts and VARIABLES."""
    return playbook(directory, f"{host},", variables, tasks)


def validate_task(role):
    return {"name": "Validate fixture", "ansible.builtin.import_role": {"name": role, "tasks_from": "validate"}}


def run_role(role, directory, variables, templates=(), host="nas_server"):
    """Import ROLE's validate tasks, then render each template name into DIRECTORY."""
    tasks = [validate_task(role)]
    for source in templates:
        tasks.append({
            "name": "Render fixture",
            "ansible.builtin.template": {
                "src": str(ROOT / "ansible/roles" / role / "templates" / (source + ".j2")),
                "dest": str(Path(directory) / source),
                "mode": "0600",
            },
        })
    return run_play(directory, variables, tasks, host)


def run_cases(directory, cases, tasks):
    """Run TASKS once for each variable set in CASES, all in one ansible-playbook run.

    Each case becomes its own fake host, so a failure stops only that case. Returns the
    run and, per case, its recap counts (such as changed and failed) and the output lines
    of its failed tasks.
    """
    hosts = {f"case{index}": variables for index, variables in enumerate(cases)}
    inventory = Path(directory) / "cases.yml"
    inventory.write_text(yaml.safe_dump({"all": {"hosts": hosts}}))
    # One line per task result, so each failure can be attributed to its host.
    result = playbook(directory, str(inventory), {}, tasks, forks=25,
                      env={"ANSIBLE_CALLBACK_FORMAT_PRETTY": "0"})
    outcomes = []
    for host in hosts:
        recap = re.search(rf"^{host}\s+:(.*)$", result.stdout, re.MULTILINE)
        if not recap:
            raise AssertionError(result.stdout)
        outcome = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", recap.group(1))}
        outcome["failures"] = re.findall(rf"^(?:fatal|failed): \[{host}\].*$", result.stdout, re.MULTILINE)
        outcomes.append(outcome)
    return result, outcomes


def assert_cases_fail_validation(test, directory, variables, cases, tasks, secrets=()):
    """Check that VARIABLES with each override in CASES fails an assertion in TASKS.

    SECRETS must not appear anywhere in the output.
    """
    result, outcomes = run_cases(directory, [{**variables, **extra} for extra in cases], tasks)
    for extra, outcome in zip(cases, outcomes):
        with test.subTest(extra=extra):
            test.assertTrue(outcome["failed"], result.stdout)
            test.assertIn('"evaluated_to": false', "\n".join(outcome["failures"]))
    for secret in secrets:
        test.assertNotIn(secret, result.stdout)
