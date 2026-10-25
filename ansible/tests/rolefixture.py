"""Run a role's validation and render its templates offline with ansible-playbook."""

import os
from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
ANSIBLE = ROOT / ".venv/bin/ansible-playbook"
TEMP_ROOT = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None


def run_play(directory, variables, tasks, host="nas_server"):
    """Run TASKS against a local fake HOST with Debian facts and VARIABLES."""
    play = [{"name": "Check fixtures", "hosts": "all", "gather_facts": False,
             "vars": {"ansible_facts": {"distribution": "Debian"}, **variables}, "tasks": tasks}]
    path = Path(directory) / "play.yml"
    path.write_text(yaml.safe_dump(play))
    return subprocess.run(
        [str(ANSIBLE), "-i", f"{host},", "-c", "local", "--diff", str(path)],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={**os.environ, "ANSIBLE_NOCOLOR": "1"}, timeout=60,
    )


def run_role(role, directory, variables, templates=(), host="nas_server"):
    """Import ROLE's validate tasks, then render each template name into DIRECTORY."""
    tasks = [{"name": "Validate fixture", "ansible.builtin.import_role": {
        "name": role, "tasks_from": "validate"}}]
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
