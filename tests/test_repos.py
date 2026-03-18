from pathlib import Path
from unittest.mock import patch

import pytest

from autopilot.repos import (
    fetch_remote_skills,
    parse_github_tree_url,
    repo_name_from_url,
    resolve_working_directory,
)


class TestParseGithubTreeUrl:
    def test_basic_url(self):
        owner, repo, ref, path = parse_github_tree_url(
            "https://github.com/polymerdao/infra/tree/main/skills/polymer-infra"
        )
        assert owner == "polymerdao"
        assert repo == "infra"
        assert ref == "main"
        assert path == "skills/polymer-infra"

    def test_nested_path(self):
        owner, repo, ref, path = parse_github_tree_url(
            "https://github.com/org/repo/tree/v2/deep/nested/skill"
        )
        assert owner == "org"
        assert repo == "repo"
        assert ref == "v2"
        assert path == "deep/nested/skill"

    def test_trailing_slash_stripped(self):
        owner, repo, ref, path = parse_github_tree_url(
            "https://github.com/org/repo/tree/main/skills/foo/"
        )
        assert path == "skills/foo"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Invalid GitHub tree URL"):
            parse_github_tree_url("https://github.com/org/repo")

    def test_not_github_raises(self):
        with pytest.raises(ValueError, match="Invalid GitHub tree URL"):
            parse_github_tree_url("https://gitlab.com/org/repo/tree/main/foo")

    def test_no_path_after_ref_raises(self):
        with pytest.raises(ValueError, match="Invalid GitHub tree URL"):
            parse_github_tree_url("https://github.com/org/repo/tree/main")


class TestRepoNameFromUrl:
    def test_https_url(self):
        assert repo_name_from_url("https://github.com/polymerdao/proof-api") == "proof-api"

    def test_https_url_with_git_suffix(self):
        assert repo_name_from_url("https://github.com/polymerdao/proof-api.git") == "proof-api"

    def test_https_url_trailing_slash(self):
        assert repo_name_from_url("https://github.com/polymerdao/proof-api/") == "proof-api"

    def test_ssh_url(self):
        assert repo_name_from_url("git@github.com:polymerdao/proof-api.git") == "proof-api"

    def test_simple_name(self):
        assert repo_name_from_url("https://github.com/org/my-repo") == "my-repo"


class TestResolveWorkingDirectory:
    def test_none_returns_none(self):
        assert resolve_working_directory(None, {}) is None

    def test_matches_repo_name(self, tmp_path):
        repos = {"proof-api": tmp_path / "proof-api"}
        result = resolve_working_directory("proof-api", repos)
        assert result == tmp_path / "proof-api"

    def test_absolute_path_passthrough(self):
        result = resolve_working_directory("/some/path", {})
        assert result == Path("/some/path")

    def test_repo_name_takes_priority(self, tmp_path):
        repos = {"myrepo": tmp_path / "myrepo"}
        result = resolve_working_directory("myrepo", repos)
        assert result == tmp_path / "myrepo"


class TestFetchRemoteSkills:
    async def test_clones_and_returns_skill_path(self, tmp_path):
        """First fetch clones the repo, returns the skill directory path."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        url = "https://github.com/org/repo/tree/main/skills/my-skill"

        cache_path = base_dir / ".skill-repos" / "org" / "repo" / "main"

        async def fake_run(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "clone":
                cache_path.mkdir(parents=True, exist_ok=True)
                (cache_path / ".git").mkdir()
                skill_dir = cache_path / "skills" / "my-skill"
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\n")
            return (0, "", "")

        with patch("autopilot.repos.run_command_async", side_effect=fake_run):
            paths = await fetch_remote_skills([url], base_dir)

        assert len(paths) == 1
        assert paths[0] == cache_path / "skills" / "my-skill"

    async def test_fetches_existing_repo(self, tmp_path):
        """Second fetch does git fetch + reset instead of clone."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        url = "https://github.com/org/repo/tree/main/skills/my-skill"

        cache_path = base_dir / ".skill-repos" / "org" / "repo" / "main"
        cache_path.mkdir(parents=True)
        (cache_path / ".git").mkdir()
        skill_dir = cache_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\n")

        calls = []

        async def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return (0, "", "")

        with patch("autopilot.repos.run_command_async", side_effect=fake_run):
            paths = await fetch_remote_skills([url], base_dir)

        assert len(paths) == 1
        assert calls[0] == ["git", "fetch", "origin", "main"]

    async def test_missing_skill_md_raises(self, tmp_path):
        """Raise error if SKILL.md doesn't exist at the specified path."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        url = "https://github.com/org/repo/tree/main/skills/missing"

        cache_path = base_dir / ".skill-repos" / "org" / "repo" / "main"

        async def fake_run(cmd, **kwargs):
            if cmd[0] == "git" and cmd[1] == "clone":
                cache_path.mkdir(parents=True, exist_ok=True)
                (cache_path / ".git").mkdir()
            return (0, "", "")

        with patch("autopilot.repos.run_command_async", side_effect=fake_run):
            with pytest.raises(FileNotFoundError, match="missing"):
                await fetch_remote_skills([url], base_dir)

    async def test_clone_failure_raises(self, tmp_path):
        """Raise error if git clone fails."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        url = "https://github.com/org/repo/tree/main/skills/foo"

        async def fake_run(cmd, **kwargs):
            return (128, "", "fatal: repo not found")

        with patch("autopilot.repos.run_command_async", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="Failed to clone"):
                await fetch_remote_skills([url], base_dir)

    async def test_deduplicates_same_repo_ref(self, tmp_path):
        """Two skills from the same repo/ref should only clone once."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        urls = [
            "https://github.com/org/repo/tree/main/skills/skill-a",
            "https://github.com/org/repo/tree/main/skills/skill-b",
        ]

        cache_path = base_dir / ".skill-repos" / "org" / "repo" / "main"
        clone_count = 0

        async def fake_run(cmd, **kwargs):
            nonlocal clone_count
            if cmd[0] == "git" and cmd[1] == "clone":
                clone_count += 1
                cache_path.mkdir(parents=True, exist_ok=True)
                (cache_path / ".git").mkdir()
                for name in ("skill-a", "skill-b"):
                    sd = cache_path / "skills" / name
                    sd.mkdir(parents=True, exist_ok=True)
                    (sd / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
            return (0, "", "")

        with patch("autopilot.repos.run_command_async", side_effect=fake_run):
            paths = await fetch_remote_skills(urls, base_dir)

        assert len(paths) == 2
        assert clone_count == 1


class TestCloneOrUpdateRepos:
    @pytest.mark.asyncio
    async def test_clone_local_repo(self, tmp_path):
        """Test cloning from a local git repo."""
        from autopilot.repos import clone_or_update_repos

        # Create a source repo
        source = tmp_path / "source"
        source.mkdir()
        import subprocess

        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(source), "config", "user.email", "test@test.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=source,
            check=True,
            capture_output=True,
        )

        base_dir = tmp_path / "base"
        base_dir.mkdir()

        result = await clone_or_update_repos([str(source)], base_dir)
        assert "source" in result
        assert (result["source"] / ".git").is_dir()

    @pytest.mark.asyncio
    async def test_update_existing_repo(self, tmp_path):
        """Test that a second call fetches instead of cloning."""
        from autopilot.repos import clone_or_update_repos

        source = tmp_path / "source"
        source.mkdir()
        import subprocess

        subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(source), "config", "user.email", "test@test.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "config", "user.name", "Test"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init"],
            cwd=source,
            check=True,
            capture_output=True,
        )

        base_dir = tmp_path / "base"
        base_dir.mkdir()

        # First clone
        await clone_or_update_repos([str(source)], base_dir)
        # Second call should update, not fail
        result = await clone_or_update_repos([str(source)], base_dir)
        assert "source" in result
