"""
SDNA Defaults - Default configurations for all SDNA agents.

All agents inherit these MCPs unless explicitly overridden.
Reads from strata config file as canonical source, falls back to env vars.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from .config import HermesConfig


def _get_strata_carton_env() -> Dict[str, str]:
    """Read carton env vars from strata config file."""
    strata_path = Path.home() / ".config" / "strata" / "servers.json"
    if strata_path.exists():
        try:
            with open(strata_path) as f:
                data = json.load(f)
            return data.get("mcp", {}).get("servers", {}).get("carton", {}).get("env", {})
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def get_default_mcp_servers() -> Dict[str, Any]:
    """
    Get default MCP servers that all SDNA agents should have.

    Currently includes:
    - carton: Knowledge graph for persistent memory

    Reads from ~/.config/strata/servers.json as canonical source,
    falls back to environment variables.
    """
    # Read from strata config (canonical source)
    strata_env = _get_strata_carton_env()

    def get_val(key: str, default: str = "") -> str:
        # Prefer strata config, then env var, then default
        return strata_env.get(key) or os.environ.get(key, default)

    return {
        "carton": {
            "command": "carton-mcp",
            "args": [],
            "env": {
                "GITHUB_PAT": get_val("GITHUB_PAT"),
                "REPO_URL": get_val("REPO_URL"),
                "HEAVEN_DATA_DIR": get_val("HEAVEN_DATA_DIR", "/tmp/heaven_data"),
                "NEO4J_URI": get_val("NEO4J_URI"),
                "NEO4J_USER": get_val("NEO4J_USER"),
                "NEO4J_PASSWORD": get_val("NEO4J_PASSWORD"),
                "OPENAI_API_KEY": get_val("OPENAI_API_KEY"),
                "CHROMA_PERSIST_DIR": get_val("CHROMA_PERSIST_DIR", "/tmp/carton_chroma_db"),
            }
        }
    }


def get_default_hermes_config(
    name: str = "",
    goal: str = "",
    system_prompt: Optional[str] = None,
    max_turns: Optional[int] = None,
    model: Optional[str] = None,
    additional_mcp_servers: Optional[Dict[str, Any]] = None,
    **kwargs
) -> HermesConfig:
    """
    Create a HermesConfig with default MCP servers (including CartON).

    Args:
        name: Config identifier
        goal: Templated prompt (use {var} for interpolation)
        system_prompt: System prompt for the agent
        max_turns: Maximum iterations
        model: Model to use
        additional_mcp_servers: Extra MCP servers to add (merged with defaults)
        **kwargs: Additional HermesConfig fields

    Returns:
        HermesConfig with CartON and any additional MCPs
    """
    # Start with defaults
    mcp_servers = get_default_mcp_servers()

    # Merge any additional servers
    if additional_mcp_servers:
        mcp_servers.update(additional_mcp_servers)

    return HermesConfig(
        name=name,
        goal=goal,
        system_prompt=system_prompt,
        max_turns=max_turns,
        model=model,
        mcp_servers=mcp_servers,
        **kwargs
    )


# Convenience alias
default_config = get_default_hermes_config
