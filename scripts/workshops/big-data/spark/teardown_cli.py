"""Explicit host-local Spark teardown CLI."""
import argparse
import json
import subprocess
import sys

from teardown_runner import run_teardown


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Remove ownership-verified Spark containers, networks and generated "
            "runtime files without archiving submission evidence. "
            "Also delete the reviewed staged worker-side Spark seed/data bundle. "
            "Remove verified locked Spark/Livy image references without force or prune. "
            "Global reset handles participant workspaces and identity options. "
            "Requires root and exclusive administrative control of Docker."
        )
    )
    parser.add_argument(
        "--execute", action="store_true", required=True,
        help="Explicitly authorize scoped runtime removal.",
    )
    parser.parse_args(argv)

    try:
        result = run_teardown()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(
            f"[ERROR] Spark teardown failed; cleanup is not verified: {error}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps({
        "cleanup_verified": True,
        "changed": bool(result["container_ids"] or result["network_ids"]
                        or result.get("removed_asset_paths")
                        or result.get("removed_image_references")
                        or result.get("retry_evidence_removed")),
        "removed_container_ids": result["container_ids"],
        "removed_network_ids": result["network_ids"],
        "removed_asset_paths": result.get("removed_asset_paths", []),
        "removed_image_references": result.get("removed_image_references", []),
        "retry_evidence_removed": bool(result.get("retry_evidence_removed")),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
