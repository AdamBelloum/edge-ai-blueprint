"""Pre-write checks for trusted organiser-rendered warm-staging inputs.

No commands, downloads or filesystem mutations. The live caller must obtain
both Compose configurations from Docker Compose using the same project root
and enabled profiles, under the shared lock. reviewed_text_files must be
rendered independently from reviewed repository templates, not accepted from
participants. This gate does not validate live containers or execution readiness.
"""
import hashlib

from livy_candidate_assets import FILES, ROOT

ARCHIVE_SHA512 = (
    "50151be834bba3011fccbb564c3c9d6bf7a08af468c2082604f3c5b40ba95705a4c2e"
    "925e835bd58a58abcbeb18f3ab7bf588e01fa4f778ff9e82a4b91b9d2de"
)
ARCHIVE = "livy-transition/livy-build/livy.zip"
SHARED = {"spark-master", "spark-worker-1", "spark-client"}
CANDIDATE_SERVICES = SHARED | {"spark-livy", "spark-livy-access"}
LIVY_IMAGE = "digitafrica/livy:0.9.0-incubating-spark3.5.3"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_archive(archive):
    require(isinstance(archive, bytes) and archive,
            "A nonempty locked Livy archive is required.")
    require(hashlib.sha512(archive).hexdigest() == ARCHIVE_SHA512,
            "Livy archive differs from the reviewed release lock.")


def verify_compose_preservation(baseline, candidate):
    require(isinstance(baseline, dict) and isinstance(candidate, dict),
            "Parsed baseline and candidate Compose configurations are required.")
    require(baseline.get("name") == candidate.get("name") == "digitafrica-spark",
            "Compose project identity differs.")
    before, after = baseline.get("services"), candidate.get("services")
    require(isinstance(before, dict) and isinstance(after, dict)
            and SHARED <= set(before) <= CANDIDATE_SERVICES
            and set(after) == CANDIDATE_SERVICES,
            "Prepared one-worker direct configuration and exact candidate services are required.")
    for service in SHARED:
        require(before[service] == after[service],
                "Existing shared/direct service definition differs: " + service)
    networks = baseline.get("networks")
    require(isinstance(networks, dict)
            and set(networks) == {"spark-private", "spark-access"}
            and networks == candidate.get("networks"),
            "Existing network definitions must remain unchanged.")
    require(not baseline.get("volumes") and not candidate.get("volumes"),
            "Named volumes are outside the reviewed staging scope.")
    livy = after["spark-livy"]
    require(isinstance(livy, dict)
            and livy.get("image") == LIVY_IMAGE
            and isinstance(livy.get("build"), dict)
            and livy["build"].get("context") == ROOT + "/livy-transition/livy-build"
            and livy["build"].get("dockerfile") == "Dockerfile"
            and not livy.get("ports"),
            "Livy image, isolated build context or private endpoint differs.")
    gateway = after["spark-livy-access"]
    require(isinstance(gateway, dict)
            and gateway.get("image") == after["spark-client"].get("image")
            and gateway.get("ports") == after["spark-client"].get("ports")
            and gateway.get("profiles") == ["participant-livy"],
            "Candidate gateway image, endpoint or explicit profile differs.")


def verify_asset_inputs(files, *, reviewed_text_files):
    require(isinstance(files, dict) and set(files) == set(FILES)
            and all(isinstance(value, bytes) and value for value in files.values()),
            "Exactly six nonempty candidate assets are required.")
    require(isinstance(reviewed_text_files, dict)
            and set(reviewed_text_files) == set(FILES) - {ARCHIVE}
            and all(isinstance(value, bytes) and value
                    for value in reviewed_text_files.values()),
            "Independent reviewed renderings of all five text assets are required.")
    for name, expected in reviewed_text_files.items():
        require(files[name] == expected,
                "Candidate asset differs from reviewed rendering: " + name)
    verify_archive(files[ARCHIVE])


def verify_staging_inputs(files, *, reviewed_text_files,
                          baseline_config, candidate_config):
    verify_asset_inputs(files, reviewed_text_files=reviewed_text_files)
    verify_compose_preservation(baseline_config, candidate_config)
