"""Prepare candidate OpenFaaS manifests offline; not deployment validation."""

import json
from pathlib import Path

from lab_config import load_config


MODULE = Path(__file__).resolve().parents[1]
TEMPLATE_REVISION = "262e6a608a3f987bcbe3322d1543b44e0e4282dc"


def render_manifest(config_path, function_key):
    """Return a JSON-formatted YAML candidate for one owned exercise function.

    Absolute source paths make this a machine-local manifest. JSON is a YAML
    subset; acceptance by the pinned CLI remains a separate validation step.
    The organiser must supply the inspected node22 template revision explicitly.
    This function neither fetches templates nor invokes a build or deployment.
    """
    config = load_config(config_path, require_live=False)
    if function_key not in ("greeting", "weather"):
        raise ValueError("Only owned greeting and weather manifests are supported.")

    source = MODULE / "examples" / function_key
    for filename in ("handler.js", "package.json"):
        if not (source / filename).is_file():
            raise ValueError("Required function source files are missing.")

    name = config["functions"][function_key]
    manifest = {
        "version": "1.0",
        "provider": {
            "name": "openfaas",
            "gateway": config["gateway_url"],
        },
        "functions": {
            name: {
                "lang": "node22",
                "handler": str(source),
                "image": (
                    config["registry_repository"] + "/" + name
                    + ":" + config["image_tag"]
                ),
            }
        },
    }
    return json.dumps(manifest, indent=2) + "\n"


def write_manifest(config_path, function_key, output_path):
    """Write a new machine-local candidate without overwriting existing files."""
    text = render_manifest(config_path, function_key)
    with Path(output_path).open("x", encoding="utf-8") as handle:
        handle.write(text)
    return Path(output_path)
