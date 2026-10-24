"""Read-only local topology hints. Never claims to inventory other hosts.

No process arguments, IDs, paths, deployment identifiers or environment values
are returned; only bounded counts and platform-presence flags.
"""

import os
from pathlib import Path


def local_deployment_observations(proc_root=Path("/proc"), environ=None):
    environ = os.environ if environ is None else environ
    platform = (
        "railway"
        if any(name in environ for name in ("RAILWAY_SERVICE_ID", "RAILWAY_DEPLOYMENT_ID", "RAILWAY_REPLICA_ID"))
        else "unspecified"
    )
    count = 0
    readable = False
    try:
        entries = list(proc_root.iterdir())[:65536]
    except OSError:
        entries = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            with (entry / "cmdline").open("rb") as stream:
                parts = stream.read(8192).split(b"\0")
            readable = True
        except OSError:
            continue
        if not parts or not Path(os.fsdecode(parts[0])).name.startswith("python"):
            continue
        if any(parts[index : index + 2] == [b"-m", b"app"] for index in range(len(parts) - 1)):
            count += 1
    return {
        "platform_hint": platform,
        "app_processes_in_local_pid_namespace": min(count, 10000),
        "local_process_inventory_readable": readable,
        "multiple_local_app_processes_observed": count > 1,
        "scope": "local_pid_namespace_only_not_other_containers_services_hosts_or_database_copies",
        "global_single_runtime_verified": False,
        "outbound_ip_or_route_stability_verified": False,
    }
