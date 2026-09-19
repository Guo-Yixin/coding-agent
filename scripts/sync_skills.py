from __future__ import annotations

import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "agent" / "skills"


def workspace_root() -> Path:
    configured = os.environ.get("AI_WORKSPACE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        return Path(r"B:\ai_workspace").resolve()
    return (PROJECT_ROOT.parent / "ai_workspace").resolve()


def sync_skills() -> Path:
    target_dir = workspace_root() / "skills"
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in SOURCE_DIR.iterdir():
        if not source.is_dir():
            continue
        target = target_dir / source.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    return target_dir


def main() -> None:
    target_dir = sync_skills()
    print(f"skills synced to: {target_dir}")


if __name__ == "__main__":
    main()
