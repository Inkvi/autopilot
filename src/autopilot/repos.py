from __future__ import annotations

import logging
import re
from pathlib import Path

from autopilot.shell import run_command_async

logger = logging.getLogger(__name__)


def repo_name_from_url(url: str) -> str:
    """Extract repository name from a git URL.

    Handles HTTPS (https://github.com/org/repo.git) and SSH (git@github.com:org/repo.git).
    """
    # Strip trailing .git
    url = re.sub(r"\.git$", "", url.rstrip("/"))
    # Get last path component
    return url.split("/")[-1].split(":")[-1]


def repos_dir(base_dir: Path) -> Path:
    return base_dir / ".repos"


async def clone_or_update_repos(
    repo_urls: list[str],
    base_dir: Path,
) -> dict[str, Path]:
    """Clone or update repos, returning a mapping of repo name -> local path."""
    root = repos_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)

    result = {}
    for url in repo_urls:
        name = repo_name_from_url(url)
        local_path = root / name

        if (local_path / ".git").is_dir():
            logger.info("Updating repo %s", name)
            code, _, stderr = await run_command_async(
                ["git", "fetch", "origin"],
                cwd=local_path,
                timeout=120,
            )
            if code == 0:
                await run_command_async(
                    ["git", "reset", "--hard", "origin/HEAD"],
                    cwd=local_path,
                    timeout=30,
                )
            else:
                logger.warning("Failed to fetch %s: %s", name, stderr.strip())
        else:
            logger.info("Cloning repo %s from %s", name, url)
            code, _, stderr = await run_command_async(
                ["git", "clone", url, str(local_path)],
                timeout=300,
            )
            if code != 0:
                logger.error("Failed to clone %s: %s", name, stderr.strip())
                continue

        result[name] = local_path

    return result


def resolve_working_directory(
    working_directory: str | None,
    cloned_repos: dict[str, Path],
) -> Path | None:
    """Resolve working_directory to a local path.

    If working_directory matches a repo name from cloned_repos, return its path.
    If it's an absolute path, return it as-is.
    If None, return None.
    """
    if working_directory is None:
        return None

    # Check if it matches a cloned repo name
    if working_directory in cloned_repos:
        return cloned_repos[working_directory]

    # Absolute or relative path — resolve as before
    return Path(working_directory).expanduser().resolve()
