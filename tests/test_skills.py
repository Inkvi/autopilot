from __future__ import annotations

from pathlib import Path

from autopilot.skills import inject_skill_paths, inject_skills


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


class TestInjectSkillPaths:
    def _make_skill(self, base: Path, name: str) -> Path:
        skill_path = base / name
        skill_path.mkdir(parents=True)
        (skill_path / "SKILL.md").write_text(
            f"---\nname: {name}\n---\nInstructions.\n",
            encoding="utf-8",
        )
        (skill_path / "extra.txt").write_text("extra content", encoding="utf-8")
        return skill_path

    def test_copies_skill_into_target(self, tmp_path):
        remote = tmp_path / "remote"
        remote.mkdir()
        skill = self._make_skill(remote, "code-review")

        target = tmp_path / "worktree"
        target.mkdir()

        inject_skill_paths([skill], target)

        dest = target / ".agents" / "skills" / "code-review"
        assert dest.is_dir()
        assert not dest.is_symlink()
        assert (dest / "SKILL.md").exists()
        assert (dest / "extra.txt").read_text() == "extra content"

    def test_skips_existing_skill(self, tmp_path):
        remote = tmp_path / "remote"
        remote.mkdir()
        skill = self._make_skill(remote, "code-review")

        target = tmp_path / "worktree"
        target.mkdir()
        existing = target / ".agents" / "skills" / "code-review"
        existing.mkdir(parents=True)
        (existing / "SKILL.md").write_text("existing", encoding="utf-8")

        inject_skill_paths([skill], target)

        assert (existing / "SKILL.md").read_text() == "existing"

    def test_multiple_skills(self, tmp_path):
        remote = tmp_path / "remote"
        remote.mkdir()
        skill_a = self._make_skill(remote, "skill-a")
        skill_b = self._make_skill(remote, "skill-b")

        target = tmp_path / "worktree"
        target.mkdir()

        inject_skill_paths([skill_a, skill_b], target)

        assert (target / ".agents" / "skills" / "skill-a" / "SKILL.md").exists()
        assert (target / ".agents" / "skills" / "skill-b" / "SKILL.md").exists()

    def test_first_wins_on_duplicate_name(self, tmp_path):
        remote1 = tmp_path / "remote1"
        remote1.mkdir()
        skill1 = self._make_skill(remote1, "dupe")
        (skill1 / "marker.txt").write_text("first", encoding="utf-8")

        remote2 = tmp_path / "remote2"
        remote2.mkdir()
        skill2 = self._make_skill(remote2, "dupe")
        (skill2 / "marker.txt").write_text("second", encoding="utf-8")

        target = tmp_path / "worktree"
        target.mkdir()

        inject_skill_paths([skill1, skill2], target)

        assert (target / ".agents" / "skills" / "dupe" / "marker.txt").read_text() == "first"

    def test_empty_list_noop(self, tmp_path):
        target = tmp_path / "worktree"
        target.mkdir()
        inject_skill_paths([], target)
        assert not (target / ".agents").exists()
