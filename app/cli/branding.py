"""CLI branding configuration — supports white-labeling via environment variables.

Set these env vars to rebrand the CLI for another platform:
    CLI_NAME        Command name shown in help (default: "cadprice")
    CLI_DISPLAY_NAME  Human-friendly name (default: "CADPrice")
    CLI_ENV_PREFIX    Prefix for env vars like <PREFIX>_API_KEY (default: "CADPRICE")

Example — a platform called "rattle" using command "rat":
    CLI_NAME=rat CLI_DISPLAY_NAME=Rattle CLI_ENV_PREFIX=RAT rat ai models
"""

from __future__ import annotations

import os

CLI_NAME: str = os.environ.get("CLI_NAME", "cadprice")
CLI_DISPLAY_NAME: str = os.environ.get("CLI_DISPLAY_NAME", "CADPrice")
CLI_ENV_PREFIX: str = os.environ.get("CLI_ENV_PREFIX", "CADPRICE")

# Derived helpers
API_KEY_ENV: str = f"{CLI_ENV_PREFIX}_API_KEY"
BASE_URL_ENV: str = f"{CLI_ENV_PREFIX}_BASE_URL"
