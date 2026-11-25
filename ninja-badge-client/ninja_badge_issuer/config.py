"""
Configuration loading. The API key is read from a config file and/or
environment variables, never prompted for.

Lookup order for the config file (first existing wins):
  1. explicit path (CLI --config / load_config(path))
  2. $NINJA_BADGE_CONFIG
  3. ./ninja_badge.ini
  4. ~/.ninja_badge.ini

Environment variables override file values:
  NINJA_BADGE_API_KEY, NINJA_BADGE_API_BASE_URL,
  NINJA_BADGE_PASS_TEMPLATE_ID, NINJA_BADGE_PARTICIPATION_TEMPLATE_ID
"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .api import DEFAULT_BASE_URL

SECTION = "ninja_badge"

_ENV = {
    "api_key": "NINJA_BADGE_API_KEY",
    "base_url": "NINJA_BADGE_API_BASE_URL",
    "pass_template_id": "NINJA_BADGE_PASS_TEMPLATE_ID",
    "participation_template_id": "NINJA_BADGE_PARTICIPATION_TEMPLATE_ID",
}


@dataclass
class Config:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    pass_template_id: str = ""
    participation_template_id: str = ""
    source: Optional[str] = None  # which file was loaded, for diagnostics

    def missing_for_live(self) -> list[str]:
        out = []
        if not self.api_key:
            out.append("api_key")
        if not self.pass_template_id:
            out.append("pass_template_id")
        if not self.participation_template_id:
            out.append("participation_template_id")
        return out


def _candidate_paths(explicit: Optional[str]) -> list[Path]:
    paths = []
    if explicit:
        paths.append(Path(explicit).expanduser())
    if os.environ.get("NINJA_BADGE_CONFIG"):
        paths.append(Path(os.environ["NINJA_BADGE_CONFIG"]).expanduser())
    paths += [Path.cwd() / "ninja_badge.ini", Path.home() / ".ninja_badge.ini"]
    return paths


def load_config(path: Optional[str] = None) -> Config:
    cfg = Config()
    if path and not Path(path).expanduser().is_file():
        raise FileNotFoundError(f"Config file not found: {path}")
    for p in _candidate_paths(path):
        if p.is_file():
            parser = configparser.ConfigParser()
            parser.read(p, encoding="utf-8")
            if parser.has_section(SECTION):
                sec = parser[SECTION]
                for k in _ENV:
                    if sec.get(k):
                        setattr(cfg, k, sec.get(k).strip())
            cfg.source = str(p)
            break
    for k, env in _ENV.items():
        if os.environ.get(env):
            setattr(cfg, k, os.environ[env].strip())
    return cfg
