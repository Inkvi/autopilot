from __future__ import annotations

import sys

import pytest

from ai_automations.shell import CommandError, run_command_async


class TestCommandError:
    def test_attributes(self):
        err = CommandError(["ls", "-la"], 1, "out", "err")
        assert err.args_list == ["ls", "-la"]
        assert err.code == 1
        assert err.stdout == "out"
        assert err.stderr == "err"
        assert "command failed (1)" in str(err)


class TestRunCommandAsync:
    async def test_success(self):
        code, stdout, stderr = await run_command_async(["echo", "hello"])
        assert code == 0
        assert stdout.strip() == "hello"

    async def test_nonzero_exit(self):
        code, stdout, stderr = await run_command_async(
            [sys.executable, "-c", "import sys; sys.exit(42)"]
        )
        assert code == 42

    async def test_stderr_captured(self):
        code, stdout, stderr = await run_command_async(
            [sys.executable, "-c", "import sys; sys.stderr.write('oops')"]
        )
        assert code == 0
        assert "oops" in stderr

    async def test_timeout_raises(self):
        with pytest.raises(TimeoutError):
            await run_command_async(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=1,
            )

    async def test_cwd(self, tmp_path):
        code, stdout, _ = await run_command_async(["pwd"], cwd=tmp_path)
        assert code == 0
        # Resolve both to handle macOS /private/var symlink
        assert tmp_path.resolve().as_posix() in stdout.strip() or str(tmp_path) in stdout.strip()

    async def test_env_override(self):
        code, stdout, _ = await run_command_async(
            [sys.executable, "-c", "import os; print(os.environ.get('TEST_VAR', ''))"],
            env={"TEST_VAR": "hello_test"},
        )
        assert code == 0
        assert "hello_test" in stdout
