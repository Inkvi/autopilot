from pathlib import Path

import pytest

from autopilot.repos import repo_name_from_url, resolve_working_directory


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
