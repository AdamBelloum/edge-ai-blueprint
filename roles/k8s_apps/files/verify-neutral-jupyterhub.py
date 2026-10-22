"""Read-only neutral JupyterHub release checks; no cleanup-completion mutation."""
import ast
import json
import subprocess
import sys


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(command):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Cannot retrieve verification evidence.") from None
    require(result.returncode == 0, "Cannot retrieve verification evidence.")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise RuntimeError("Invalid verification evidence.") from None


def dictionaries(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from dictionaries(child)
    elif isinstance(value, list):
        for child in value:
            yield from dictionaries(child)


def verify(values, state, deployments):
    expected = {
        "workshop_type": "none",
        "workshop_module": "none",
        "mode": "beginner",
        "solutions_released": "false",
        "cleanup_status": "in_progress",
    }
    require(
        all(state.get("data", {}).get(key) == value
            for key, value in expected.items()),
        "Workshop state is not neutral with cleanup in progress.",
    )

    hook = values.get("hub", {}).get("extraConfig", {}).get(
        "10-digitafrica-group-workspace"
    )
    require(isinstance(hook, str), "Group-workspace hook is absent.")
    try:
        tree = ast.parse(hook)
    except SyntaxError:
        raise RuntimeError("Group-workspace hook is invalid.") from None

    assignments = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value

    for name in ("BIG_DATA_WORKSPACE_ENABLED", "HPC_WORKSPACE_ENABLED"):
        value = assignments.get(name)
        require(
            isinstance(value, ast.Constant) and value.value is False,
            "Workshop-specific source integration remains enabled.",
        )

    forbidden_functions = {
        "configure_digitafrica_spark_source",
        "configure_digitafrica_hpc_source",
        "configure_digitafrica_module5_node_launch",
        "configure_digitafrica_module5_node_preparation",
        "read_digitafrica_module5_workshop_state",
    }
    require(
        not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in forbidden_functions
            for node in ast.walk(tree)
        ),
        "Optional workshop handlers remain in the release hook.",
    )
    require(
        not any(
            isinstance(node, ast.Constant)
            and node.value == "digitafrica-workshop"
            for node in ast.walk(tree)
        ),
        "Participant workshop data mount remains in the release hook.",
    )
    require(
        any(
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "configure_digitafrica_group_workspace"
            for node in tree.body
        ),
        "Participant authorization and placement hook is absent.",
    )
    require(
        any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Attribute)
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "c"
                and target.value.attr == "KubeSpawner"
                and target.attr == "pre_spawn_hook"
                for target in node.targets
            )
            and isinstance(node.value, ast.Name)
            and node.value.id == "configure_digitafrica_group_workspace"
            for node in tree.body
        ),
        "Participant pre-spawn hook is not registered.",
    )

    singleuser = values.get("singleuser", {})
    forbidden_volumes = {
        "digitafrica-workshop",
        "digitafrica-spark-source",
        "digitafrica-hpc-source",
        "digitafrica-runtime-hpc",
        "digitafrica-runtime-module5-node",
        "digitafrica-seed-cloud-computing-soa-module5-beginner",
    }
    require(
        not any(
            item.get("name") in forbidden_volumes
            or (
                isinstance(item.get("name"), str)
                and item["name"].startswith(
                    "digitafrica-seed-cloud-computing-soa-module3-"
                )
            )
            for item in dictionaries(singleuser)
        ),
        "Optional workshop volumes or mounts remain in the release.",
    )
    containers = singleuser.get("initContainers", [])
    require(
        not any(item.get("name") in {
            "prepare-hpc-home",
            "prepare-hpc-runtime",
            "prepare-module5-node-runtime",
        } for item in containers),
        "Optional workshop preparation containers remain in the release.",
    )
    require(
        sum(item.get("name") == "seed-notebooks" for item in containers) == 1,
        "Notebook seeder is absent or ambiguous.",
    )

    items = deployments.get("items", [])
    require(bool(items), "No JupyterHub release deployments found.")
    require(
        any(
            any(container.get("name") == "hub" for container in
                item.get("spec", {}).get("template", {}).get("spec", {}).get(
                    "containers", []
                ))
            for item in items
        ),
        "Hub deployment is absent from rollout evidence.",
    )
    for item in items:
        metadata = item.get("metadata", {})
        status = item.get("status", {})
        desired = item.get("spec", {}).get("replicas", 1)
        require(
            desired > 0
            and status.get("observedGeneration", 0)
                >= metadata.get("generation", 1)
            and status.get("replicas", 0) == desired
            and status.get("updatedReplicas", 0) == desired
            and status.get("readyReplicas", 0) == desired
            and status.get("availableReplicas", 0) == desired,
            "JupyterHub deployment rollout is incomplete.",
        )


def execute(namespace, read=load):
    kubectl = ["k3s", "kubectl", "-n", namespace]
    state_command = kubectl + [
        "get", "configmap", "digitafrica-workshop-state", "-o", "json"
    ]
    initial_state = read(state_command)
    values = read([
        "helm", "-n", namespace, "get", "values", "jhub", "-o", "json"
    ])
    deployments = read(kubectl + [
        "get", "deployment", "-l", "app.kubernetes.io/instance=jhub",
        "-o", "json",
    ])
    verify(values, initial_state, deployments)
    final_state = read(state_command)
    verify(values, final_state, deployments)
    version = initial_state.get("metadata", {}).get("resourceVersion")
    require(
        bool(version)
        and final_state.get("metadata", {}).get("resourceVersion") == version,
        "Workshop state changed during verification; retry required.",
    )
    print("Neutral JupyterHub release configuration and rollout checks passed.")
    print("Effective Hub configuration and fresh notebook startup: NOT VALIDATED.")
    print("Cleanup completion is not authorized by these checks.")


if __name__ == "__main__":
    try:
        require(len(sys.argv) == 2, "Expected one namespace argument.")
        execute(sys.argv[1])
    except (RuntimeError, ValueError, KeyError, TypeError, AttributeError):
        # Do not expose retrieved Helm values, command output or tracebacks.
        print(
            "ERROR: Neutral JupyterHub verification failed; "
            "cleanup must remain in_progress.",
            file=sys.stderr,
        )
        sys.exit(1)
