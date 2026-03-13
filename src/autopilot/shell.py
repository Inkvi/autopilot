from __future__ import annotations

import asyncio
import os
from pathlib import Path


class CommandError(RuntimeError):
    def __init__(self, args: list[str], code: int, stdout: str, stderr: str) -> None:
        self.args_list = args
        self.code = code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"command failed ({code}): {' '.join(args)}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )


async def run_command_async(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    merged_env = None
    if env is not None:
        merged_env = {**os.environ, **env}
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=merged_env,
    )

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    return proc.returncode or 0, stdout, stderr
