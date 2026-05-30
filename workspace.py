"""Workspace management - isolated environments for different content domains.

Each workspace has its own feeds.json, database, and preferences.
Default workspace preserves existing data structure.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

DEFAULT_WORKSPACE = "default"
WORKSPACE_DIR = "workspaces"


def get_workspace_root() -> Path:
    """Get the root directory for all workspaces."""
    return Path(os.environ.get("WORKSPACE_ROOT", WORKSPACE_DIR))


def list_workspaces() -> list[str]:
    """List all available workspace names."""
    root = get_workspace_root()
    if not root.exists():
        return [DEFAULT_WORKSPACE]
    dirs = [d.name for d in root.iterdir() if d.is_dir() and (d / "feeds.json").exists()]
    if DEFAULT_WORKSPACE not in dirs:
        dirs.insert(0, DEFAULT_WORKSPACE)
    return sorted(dirs)


def get_workspace_path(name: str) -> Path:
    """Get the path to a workspace directory."""
    if name == DEFAULT_WORKSPACE:
        # Default workspace uses project root (backward compatible)
        return Path(".")
    return get_workspace_root() / name


def get_feeds_path(workspace: str = DEFAULT_WORKSPACE) -> Path:
    """Get feeds.json path for a workspace."""
    return get_workspace_path(workspace) / "feeds.json"


def get_db_path(workspace: str = DEFAULT_WORKSPACE) -> str:
    """Get database path for a workspace."""
    ws_path = get_workspace_path(workspace)
    if workspace == DEFAULT_WORKSPACE:
        return str(ws_path / "knowledge" / "signal.db")
    return str(ws_path / "signal.db")


def workspace_exists(name: str) -> bool:
    """Check if a workspace exists."""
    if name == DEFAULT_WORKSPACE:
        return True
    ws_path = get_workspace_path(name)
    return ws_path.exists() and (ws_path / "feeds.json").exists()


def create_workspace(name: str, feeds: list[dict] | None = None) -> Path:
    """Create a new workspace with optional initial feeds.

    Args:
        name: Workspace name (must be valid directory name)
        feeds: Optional list of feed configs. If None, creates empty feeds.json.

    Returns:
        Path to the created workspace directory.

    Raises:
        ValueError: If name is invalid or workspace already exists.
    """
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"Invalid workspace name: {name}")
    if workspace_exists(name):
        raise ValueError(f"Workspace '{name}' already exists")

    ws_path = get_workspace_path(name)
    ws_path.mkdir(parents=True, exist_ok=True)

    # Create feeds.json
    feeds_data = feeds or []
    (ws_path / "feeds.json").write_text(json.dumps(feeds_data, indent=2, ensure_ascii=False))

    return ws_path


def delete_workspace(name: str) -> None:
    """Delete a workspace and all its data.

    Raises:
        ValueError: If trying to delete the default workspace or workspace doesn't exist.
    """
    if name == DEFAULT_WORKSPACE:
        raise ValueError("Cannot delete the default workspace")
    if not workspace_exists(name):
        raise ValueError(f"Workspace '{name}' does not exist")

    ws_path = get_workspace_path(name)
    shutil.rmtree(ws_path)


def get_active_workspace() -> str:
    """Get the currently active workspace from environment or default."""
    return os.environ.get("ACTIVE_WORKSPACE", DEFAULT_WORKSPACE)
