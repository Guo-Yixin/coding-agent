"""Backward-compatible imports for the shared repository model.

The canonical implementation lives in :mod:`agent.repository`. This module
keeps existing imports working while avoiding initialization cycles in the
tools package.
"""

from agent.repository import (
    SUPPORTED_PROVIDERS,
    Repository,
    get_provider_token,
    mask_tokens,
    normalize_repo_url,
    parse_repo_url,
    project_dir,
    provider_for_host,
)

__all__ = [
    "SUPPORTED_PROVIDERS",
    "Repository",
    "get_provider_token",
    "mask_tokens",
    "normalize_repo_url",
    "parse_repo_url",
    "project_dir",
    "provider_for_host",
]
