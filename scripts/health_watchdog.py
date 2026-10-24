#!/usr/bin/env python3
"""Optional HOST-side health watchdog; standard library, no app credentials.

Restarts ONE existing unhealthy app container sequentially; never creates a
container, scales workers, changes data/config or clears session safety. Docker
restart policy still handles ordinary process exits. Run by the optional timer.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid watchdog arguments. Use --help; never pass credentials.\n")


def docker_output(binary, arguments, timeout=20):
    result = subprocess.run([binary, *arguments], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Docker operation failed")
    return result.stdout.strip()


def inspect_and_restart(project, state_dir, docker="docker", reference=None, dry_run=False):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
        return {"status": "refused", "reason": "invalid_compose_project"}, 2
    try:
        directory = Path(state_dir)
        if directory.is_symlink():
            return {"status": "refused", "reason": "unsafe_watchdog_state_path"}, 2
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(directory / (project + ".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"status": "skipped", "reason": "another_watchdog_run_holds_project_lock"}, 0
            return inspect_locked(project, directory, docker, reference, dry_run)
    except Exception:
        return {"status": "failed", "reason": "docker_or_watchdog_state_unavailable"}, 1


def inspect_locked(project, state_dir, docker, reference, dry_run):
    reference = int(time.time()) if reference is None else int(reference)
    try:
        ids = docker_output(
            docker,
            ["ps", "-aq", "--filter", "label=com.docker.compose.project=" + project, "--filter", "label=com.docker.compose.service=app"],
        ).split()
        if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{12,64}", ids[0]):
            return {"status": "refused", "reason": "not_exactly_one_existing_app_container"}, 2
        state = json.loads(docker_output(docker, ["inspect", "--format", "{{json .State}}", ids[0]]))
        if state.get("Running") is not True or state.get("Restarting") is True:
            return {"status": "skipped", "reason": "stopped_or_restarting_no_start_requested"}, 0
        health = state.get("Health", {}).get("Status")
        if health in {"healthy", "starting"}:
            return {"status": "skipped", "reason": "healthy_or_starting"}, 0
        if health != "unhealthy":
            return {"status": "refused", "reason": "no_reliable_health_state"}, 2
        directory = Path(state_dir)
        if directory.is_symlink():
            return {"status": "refused", "reason": "unsafe_watchdog_state_path"}, 2
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        file = directory / (project + ".last_restart")
        if file.is_symlink():
            return {"status": "refused", "reason": "unsafe_watchdog_state_file"}, 2
        previous = int(file.read_text().strip()) if file.exists() else None
        if previous is not None and reference - previous < 900:
            return {"status": "skipped", "reason": "restart_cooldown_15_minutes"}, 0
        if dry_run:
            return {"status": "would_restart", "reason": "one_existing_unhealthy_app"}, 0
        # Persist throttle BEFORE asking Docker: a timed-out CLI can leave a
        # daemon-owned restart in progress. Do not initiate a second restart.
        fd, temporary = tempfile.mkstemp(prefix=".watchdog-", dir=directory)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(str(reference) + "\n")
            os.replace(temporary, file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        # Re-check after persistence; a stopped service stays stopped. For
        # deliberate maintenance stop the timer FIRST to eliminate the final
        # inspect/restart race with an independent operator command.
        latest = json.loads(docker_output(docker, ["inspect", "--format", "{{json .State}}", ids[0]]))
        if latest.get("Running") is not True or latest.get("Restarting") is True or latest.get("Health", {}).get("Status") != "unhealthy":
            return {"status": "skipped", "reason": "container_state_changed_before_restart"}, 0
        docker_output(docker, ["restart", "--time", "300", ids[0]], timeout=360)
        return {"status": "restarted", "reason": "old_container_stopped_before_same_container_restart"}, 0
    except Exception:
        # Never dump inspect output, process arguments, stderr, environment or
        # a raw exception that may contain private deployment metadata.
        return {"status": "failed", "reason": "docker_or_watchdog_state_unavailable"}, 1


def main(argv=None):
    parser = SafeParser(description="Optional host-only watchdog for ONE existing Compose app; no session/data access.")
    parser.add_argument("--project", default=os.getenv("TELEPILOT_COMPOSE_PROJECT"))
    parser.add_argument("--state-dir", default="/var/lib/telepilot-watchdog")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.project:
        print(json.dumps({"status": "refused", "reason": "set_the_existing_compose_project_explicitly"}))
        return 2
    report, result = inspect_and_restart(args.project, args.state_dir, args.docker, dry_run=args.dry_run)
    print(json.dumps(report, sort_keys=True))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
