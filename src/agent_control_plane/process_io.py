from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path


@dataclass(frozen=True)
class BoundedProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    duration_ms: int
    timed_out: bool
    output_limited: bool


def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    max_output_bytes: int,
    input_bytes: bytes | None = None,
) -> BoundedProcessResult:
    if not argv:
        raise ValueError("argv must not be empty")
    if not isfinite(timeout_seconds) or timeout_seconds <= 0 or max_output_bytes < 1:
        raise ValueError("process limits must be positive")

    started = time.monotonic()
    process = subprocess.Popen(  # noqa: S603 - caller must policy-check argv
        list(argv),
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=os.name == "posix",
    )
    assert process.stdout is not None
    assert process.stderr is not None

    stdout = bytearray()
    stderr = bytearray()
    output_limited = threading.Event()
    lock = threading.Lock()
    captured_total = 0

    def read_stream(stream, target: bytearray) -> None:
        nonlocal captured_total
        try:
            while chunk := stream.read(8_192):
                with lock:
                    remaining = max_output_bytes - captured_total
                    if remaining > 0:
                        kept = chunk[:remaining]
                        target.extend(kept)
                        captured_total += len(kept)
                    if len(chunk) > max(0, remaining):
                        output_limited.set()
                        _kill_process_tree(process)
                        break
        finally:
            stream.close()

    readers = (
        threading.Thread(target=read_stream, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=read_stream, args=(process.stderr, stderr), daemon=True),
    )
    for reader in readers:
        reader.start()

    writer: threading.Thread | None = None
    if input_bytes is not None:
        stdin = process.stdin
        assert stdin is not None

        def write_input() -> None:
            try:
                stdin.write(input_bytes)
                stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                stdin.close()

        writer = threading.Thread(target=write_input, daemon=True)
        writer.start()

    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(process)
        process.wait()

    if writer is not None:
        writer.join(timeout=1)
    for reader in readers:
        reader.join(timeout=1)

    returncode = process.returncode
    if timed_out:
        returncode = 124
    elif output_limited.is_set():
        returncode = 125
    return BoundedProcessResult(
        returncode=returncode,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
        duration_ms=int((time.monotonic() - started) * 1_000),
        timed_out=timed_out,
        output_limited=output_limited.is_set(),
    )


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
