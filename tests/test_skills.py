from __future__ import annotations

from pathlib import Path

from autopilot.skills import inject_skills


class TestInjectSkills:
    def _make_skill(self, skills_dir: Path, name: str) -> Path:
        """Create a minimal valid skill folder."""
        skill_path = skills_dir / name
        skill_path.mkdir(parents=True)
        (skill_path / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Test skill\n---\nInstructions here.\n",
            encoding="utf-8",
        )
        return skill_path

    def test_symlinks_skills(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        self._make_skill(skills_dir, "code-review")

        target = tmp_path / "worktree"
        target.mkdir()

        inject_skills(skills_dir, target)

        link = target / ".agents" / "skills" / "code-review"
        assert link.is_symlink()
        assert link.resolve() == (skills_dir / "code-review").resolve()

    def test_creates_agents_skills_dir(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        self._make_skill(skills_dir, "lint")

        target = tmp_path / "worktree"
        target.mkdir()

        inject_skills(skills_dir, target)
        assert (target / ".agents" / "skills").is_dir()

    def test_skips_existing_skill(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        self._make_skill(skills_dir, "code-review")

        target = tmp_path / "worktree"
        target.mkdir()
        existing = target / ".agents" / "skills" / "code-review"
        existing.mkdir(parents=True)
        (existing / "SKILL.md").write_text("existing", encoding="utf-8")

        inject_skills(skills_dir, target)

        assert not (target / ".agents" / "skills" / "code-review").is_symlink()
        assert (existing / "SKILL.md").read_text() == "existing"

    def test_skips_folders_without_skill_md(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "not-a-skill").mkdir()

        target = tmp_path / "worktree"
        target.mkdir()

        inject_skills(skills_dir, target)
        assert not (target / ".agents" / "skills" / "not-a-skill").exists()

    def test_multiple_skills(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        self._make_skill(skills_dir, "code-review")
        self._make_skill(skills_dir, "lint")

        target = tmp_path / "worktree"
        target.mkdir()

        inject_skills(skills_dir, target)

        assert (target / ".agents" / "skills" / "code-review").is_symlink()
        assert (target / ".agents" / "skills" / "lint").is_symlink()

    def test_empty_skills_dir(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        target = tmp_path / "worktree"
        target.mkdir()

        inject_skills(skills_dir, target)

    def test_nonexistent_skills_dir(self, tmp_path: Path):
        target = tmp_path / "worktree"
        target.mkdir()

        inject_skills(tmp_path / "no-skills", target)
