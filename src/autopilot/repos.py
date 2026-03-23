from __future__ import annotations

import logging
import re
import shutil
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


_GITHUB_TREE_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$")


def parse_github_tree_url(url: str) -> tuple[str, str, str, str]:
    """Parse a GitHub tree URL into (owner, repo, ref, path).

    Example: https://github.com/org/repo/tree/main/skills/foo
    Returns: ("org", "repo", "main", "skills/foo")
    """
    url = url.rstrip("/")
    m = _GITHUB_TREE_RE.match(url)
    if not m:
        raise ValueError(
            f"Invalid GitHub tree URL: {url!r}. "
            f"Expected: https://github.com/{{owner}}/{{repo}}/tree/{{ref}}/{{path}}"
        )
    return m.group(1), m.group(2), m.group(3), m.group(4)


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
                await run_command_async(
                    ["git", "clean", "-fd"],
                    cwd=local_path,
                    timeout=30,
                )
            else:
                logger.warning("Failed to fetch %s: %s", name, stderr.strip())
        else:
            if local_path.exists():
                logger.warning("Removing incomplete repo directory %s before cloning", name)
                shutil.rmtree(local_path)
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


def _skill_repos_dir(base_dir: Path) -> Path:
    return base_dir / ".skill-repos"


async def fetch_remote_skills(
    urls: list[str],
    base_dir: Path,
) -> list[Path]:
    """Fetch remote skills from GitHub tree URLs.

    Clones or updates repos, validates SKILL.md exists.
    Returns list of resolved skill directory paths.
    Raises on any failure (clone, fetch, or missing SKILL.md).
    """
    root = _skill_repos_dir(base_dir)
    root.mkdir(parents=True, exist_ok=True)

    # Group by (owner, repo, ref) to deduplicate clones
    parsed: list[tuple[str, str, str, str]] = []
    for url in urls:
        parsed.append(parse_github_tree_url(url))

    # Clone/fetch unique repos
    fetched: set[tuple[str, str, str]] = set()
    for owner, repo, ref, _ in parsed:
        key = (owner, repo, ref)
        if key in fetched:
            continue
        fetched.add(key)

        local_path = root / owner / repo / ref
        repo_url = f"https://github.com/{owner}/{repo}.git"

        if (local_path / ".git").is_dir():
            logger.info("Updating skill repo %s/%s@%s", owner, repo, ref)
            code, _, stderr = await run_command_async(
                ["git", "fetch", "origin", ref],
                cwd=local_path,
                timeout=120,
            )
            if code == 0:
                await run_command_async(
                    ["git", "reset", "--hard", "FETCH_HEAD"],
                    cwd=local_path,
                    timeout=30,
                )
            else:
                raise RuntimeError(
                    f"Failed to fetch skill repo {owner}/{repo}@{ref}: {stderr.strip()}"
                )
        else:
            logger.info("Cloning skill repo %s/%s@%s", owner, repo, ref)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            code, _, stderr = await run_command_async(
                ["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(local_path)],
                timeout=300,
            )
            if code != 0:
                raise RuntimeError(
                    f"Failed to clone skill repo {owner}/{repo}@{ref}: {stderr.strip()}"
                )

    # Resolve and validate skill paths
    result: list[Path] = []
    for owner, repo, ref, path in parsed:
        skill_dir = root / owner / repo / ref / path
        if not (skill_dir / "SKILL.md").exists():
            raise FileNotFoundError(
                f"Skill not found: {path} in {owner}/{repo}@{ref} (no SKILL.md at {skill_dir})"
            )
        result.append(skill_dir)

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
