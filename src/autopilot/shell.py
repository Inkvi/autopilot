from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
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
    log_file: Path | None = None,
    on_output: Callable[[str], None] | None = None,
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

    if log_file is None and on_output is None:
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        return proc.returncode or 0, stdout, stderr

    # Streaming mode: read line-by-line, write to log file and/or call callback
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    fh = open(log_file, "w", encoding="utf-8") if log_file else None

    async def _read_stream(stream, acc):
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace")
            acc.append(decoded)
            if fh:
                fh.write(decoded)
                fh.flush()
            if on_output:
                on_output(decoded.rstrip("\n"))

    assert proc.stdout is not None
    assert proc.stderr is not None
    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(proc.stdout, stdout_parts),
                _read_stream(proc.stderr, stderr_parts),
            ),
            timeout=timeout,
        )
        await proc.wait()
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    finally:
        if fh:
            fh.close()

    return proc.returncode or 0, "".join(stdout_parts), "".join(stderr_parts)
