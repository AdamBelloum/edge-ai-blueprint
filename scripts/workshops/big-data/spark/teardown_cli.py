"""Explicit host-local Spark teardown CLI."""
import argparse
import json
import subprocess
import sys

from teardown_runner import run_teardown


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Remove ownership-verified managed Spark containers and networks. "
            "Preserves images, datasets and staged runtime assets. "
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
        "changed": bool(result["container_ids"] or result["network_ids"]),
        "removed_container_ids": result["container_ids"],
        "removed_network_ids": result["network_ids"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
