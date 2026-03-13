from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def inject_skills(skills_dir: Path, target_cwd: Path) -> None:
    """Symlink individual skill folders into target_cwd/.agents/skills/.

    For each subfolder in skills_dir containing a SKILL.md:
    - If target_cwd/.agents/skills/<name> already exists: skip (repo's version wins)
    - Otherwise: create symlink

    Does nothing if skills_dir doesn't exist or is empty.
    """
    if not skills_dir.is_dir():
        return

    agents_skills = target_cwd / ".agents" / "skills"
    has_skills = False

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "SKILL.md").exists():
            logger.debug("Skipping %s — no SKILL.md", entry.name)
            continue

        if not has_skills:
            agents_skills.mkdir(parents=True, exist_ok=True)
            has_skills = True

        target = agents_skills / entry.name
        if target.exists():
            logger.info("Skill %s already exists in target, skipping", entry.name)
            continue

        os.symlink(entry.resolve(), target)
        logger.debug("Symlinked skill %s -> %s", entry.name, target)
