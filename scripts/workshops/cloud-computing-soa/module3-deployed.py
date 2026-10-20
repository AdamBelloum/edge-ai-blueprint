"""Module 3 deployed delivery checks; no exercise-runtime claims."""
import base64
import hashlib
import json
import subprocess
import sys


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(command):
    result = subprocess.run(command, capture_output=True, text=True)
    require(result.returncode == 0, "Cannot retrieve deployed delivery configuration.")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise RuntimeError("Invalid deployed configuration response.") from None


def dictionaries(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from dictionaries(child)
    elif isinstance(value, list):
        for child in value:
            yield from dictionaries(child)


def execute(payload, read=load, run=subprocess.run):
    namespace = payload["namespace"]
    operation = payload["operation"]
    mode = payload["mode"]
    require(mode in ("beginner", "advanced"), "Invalid Module 3 mode.")
    require(operation in ("check", "status", "publish", "release"),
            "Invalid Module 3 operation.")
    kubectl = ["k3s", "kubectl", "-n", namespace]

    def state():
        return read(kubectl + [
            "get", "configmap", "digitafrica-workshop-state", "-o", "json"
        ]).get("data", {})

    if operation == "status":
        current = state()
        for key in ("workshop_type", "workshop_module", "mode", "solutions_released"):
            print(key + "=" + str(current.get(key, "unset")))
        tracks = ("beginner", "advanced", "solutions", "tests")
    else:
        tracks = (mode, "tests")
        if operation == "release":
            current = state()
            require(
                (current.get("workshop_type"), current.get("workshop_module"),
                 current.get("mode")) ==
                ("cloud-computing-soa", "module3", "advanced"),
                "Solutions require active Cloud SOA Module 3 advanced mode."
            )
            require(mode == "advanced", "Solution release requires advanced mode.")
            tracks += ("solutions",)

    values = read(["helm", "-n", namespace, "get", "values", "jhub", "-o", "json"])
    singleuser = values.get("singleuser", {})
    seeders = [
        item for item in singleuser.get("initContainers", [])
        if item.get("name") == "seed-notebooks"
    ]
    require(len(seeders) == 1, "Notebook seeder is absent or ambiguous.")
    seed = seeders[0]
    require(
        "cloud_module3_delivery_enabled=true" in "\n".join(seed.get("args", [])),
        "Deployed notebook seeder disables Module 3 delivery."
    )

    # All four mounts are required by the configured init container, even when
    # only one teaching track and shared tests will be copied.
    for track in ("beginner", "advanced", "solutions", "tests"):
        name = "digitafrica-notebooks-cloud-computing-soa-module3-" + track
        manifest = read(kubectl + ["get", "configmap", name, "-o", "json"])
        require(manifest.get("metadata", {}).get("name") == name,
                "Unexpected Module 3 ConfigMap identity.")
        require(manifest.get("metadata", {}).get("namespace") == namespace,
                "Unexpected Module 3 ConfigMap namespace.")
        data = manifest.get("data", {})
        expected = payload["assets"][track]
        require(data.get("asset_map_tsv") == payload["map"],
                "Module 3 asset map differs from the current checkout: " + track)
        require(set(data) == set(expected) | {"asset_map_tsv"},
                "Module 3 ConfigMap keys are incomplete or unexpected: " + track)
        if track in tracks:
            for key, digest in expected.items():
                value = data.get(key)
                require(isinstance(value, str), "Missing Module 3 asset: " + key)
                require(hashlib.sha256(value.encode("utf-8")).hexdigest() == digest,
                        "Module 3 asset differs from the current checkout: " + key)

        volumes = [
            item for item in dictionaries(singleuser)
            if isinstance(item.get("configMap"), dict)
            and item["configMap"].get("name") == name
        ]
        require(len(volumes) == 1, "Module 3 seed volume absent or ambiguous: " + track)
        volume = volumes[0]
        require("items" not in volume["configMap"],
                "Unexpected restricted Module 3 seed projection: " + track)
        mounts = [
            item for item in seed.get("volumeMounts", [])
            if item.get("name") == volume.get("name")
        ]
        require(len(mounts) == 1 and
                mounts[0].get("mountPath") == "/seed/cloud-computing-soa/module3/" + track
                and mounts[0].get("readOnly") is True,
                "Module 3 read-only seed mount absent or invalid: " + track)

    deployments = read(kubectl + [
        "get", "deployment", "-l", "app.kubernetes.io/instance=jhub", "-o", "json"
    ]).get("items", [])
    require(bool(deployments), "No JupyterHub release deployments found.")
    for deployment in deployments:
        metadata = deployment.get("metadata", {})
        status = deployment.get("status", {})
        desired = deployment.get("spec", {}).get("replicas", 1)
        require(desired > 0 and
                status.get("observedGeneration", 0) >= metadata.get("generation", 1)
                and status.get("updatedReplicas", 0) == desired
                and status.get("availableReplicas", 0) >= desired,
                "JupyterHub deployment rollout is incomplete.")

    if operation in ("publish", "release"):
        if operation == "release":
            # Recheck immediately before mutation.
            current = state()
            require(
                (current.get("workshop_type"), current.get("workshop_module"),
                 current.get("mode")) ==
                ("cloud-computing-soa", "module3", "advanced"),
                "Active state changed; solution release blocked."
            )
            update = {"solutions_released": "true"}
        else:
            update = {
                "workshop_type": "cloud-computing-soa",
                "workshop_module": "module3",
                "mode": mode,
                "solutions_released": "false",
            }

        # Resource-version test prevents overwriting a concurrent state change.
        snapshot = read(kubectl + [
            "get", "configmap", "digitafrica-workshop-state", "-o", "json"
        ])
        if operation == "release":
            current = snapshot.get("data", {})
            require(
                (current.get("workshop_type"), current.get("workshop_module"),
                 current.get("mode")) ==
                ("cloud-computing-soa", "module3", "advanced"),
                "Active state changed; solution release blocked."
            )
        version = snapshot.get("metadata", {}).get("resourceVersion")
        require(bool(version), "Cannot determine workshop-state resource version.")
        patch = [
            {"op": "test", "path": "/metadata/resourceVersion", "value": version}
        ] + [
            {"op": "add", "path": "/data/" + key, "value": value}
            for key, value in update.items()
        ]
        result = run(kubectl + [
            "patch", "configmap", "digitafrica-workshop-state",
            "--type=json", "-p", json.dumps(patch)
        ], capture_output=True, text=True)
        require(result.returncode == 0,
                "Workshop-state update failed; recheck readiness and active state.")
        print("Module 3 state updated for subsequent participant spawns only.")

    print("Module 3 teaching-file delivery readiness passed.")
    print("Exercise-runtime readiness: NOT VALIDATED.")
    print("Existing participant files, accounts and credentials are unchanged.")


if __name__ == "__main__":
    try:
        execute(json.loads(base64.b64decode(sys.argv[1])))
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
