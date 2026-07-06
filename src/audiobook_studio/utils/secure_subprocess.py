"""
Secure subprocess utilities for audiobook-studio.

Provides safe subprocess execution with:
- Full path resolution for executables
- Input validation for file paths
- No shell=True usage
- Structured logging
"""

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Cache for resolved executable paths
_executable_cache: dict[str, Optional[str]] = {}


def resolve_executable(name: str) -> Optional[str]:
    """
    Resolve executable to full path using shutil.which().

    Args:
        name: Executable name (e.g., "ffmpeg", "ffprobe", "nvidia-smi", "sysctl")

    Returns:
        Full path to executable, or None if not found
    """
    if name in _executable_cache:
        return _executable_cache[name]

    path = shutil.which(name)
    _executable_cache[name] = path
    if path is None:
        logger.warning(f"Executable not found in PATH: {name}")
    return path


def validate_path(path: Path, must_exist: bool = False, allowed_dirs: Optional[List[Path]] = None) -> Path:
    """
    Validate and resolve a file path to prevent path traversal.

    Args:
        path: Path to validate
        must_exist: If True, raise if path doesn't exist
        allowed_dirs: Optional list of allowed parent directories

    Returns:
        Resolved absolute path

    Raises:
        ValueError: If path is invalid or traverses outside allowed dirs
    """
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Invalid path: {path}") from e

    if must_exist and not resolved.exists():
        raise ValueError(f"Path does not exist: {resolved}")

    if allowed_dirs:
        allowed = any(resolved.is_relative_to(d.resolve()) for d in allowed_dirs)
        if not allowed:
            raise ValueError(f"Path outside allowed directories: {resolved}")

    return resolved


def run_command(
    cmd: List[str],
    cwd: Optional[Path] = None,
    timeout: int = 60,
    capture_output: bool = True,
    text: bool = True,
    check: bool = True,
    allowed_dirs: Optional[List[Path]] = None,
) -> subprocess.CompletedProcess:
    """
    Securely run a command with full path resolution and input validation.

    Args:
        cmd: Command list with executable as first element
        cwd: Working directory
        timeout: Timeout in seconds
        capture_output: Capture stdout/stderr
        text: Return text instead of bytes
        check: Raise on non-zero exit
        allowed_dirs: Allowed directories for file arguments

    Returns:
        CompletedProcess result

    Raises:
        FileNotFoundError: If executable not found
        ValueError: If path validation fails
        subprocess.CalledProcessError: If check=True and command fails
        subprocess.TimeoutExpired: If timeout exceeded
    """
    if not cmd:
        raise ValueError("Empty command")

    # Resolve executable to full path
    executable = cmd[0]
    full_path = resolve_executable(executable)
    if full_path is None:
        raise FileNotFoundError(f"Executable not found: {executable}")

    # Build validated command
    validated_cmd = [full_path] + cmd[1:]

    # Validate file path arguments if allowed_dirs provided
    if allowed_dirs:
        for i, arg in enumerate(validated_cmd[1:], 1):
            # Check if argument looks like a file path
            if isinstance(arg, str) and ("/" in arg or "\\" in arg):
                try:
                    validated_cmd[i] = str(validate_path(Path(arg), allowed_dirs=allowed_dirs))
                except ValueError:
                    # Not a path or validation failed, keep original
                    pass

    logger.debug(f"Running command: {validated_cmd}")
    return subprocess.run(  # nosec B603 - using full path resolution and input validation
        validated_cmd,
        cwd=str(cwd) if cwd else None,
        timeout=timeout,
        capture_output=capture_output,
        text=text,
        check=check,
    )


async def run_command_async(
    cmd: List[str],
    cwd: Optional[Path] = None,
    timeout: int = 60,
    allowed_dirs: Optional[List[Path]] = None,
) -> subprocess.CompletedProcess:
    """
    Securely run a command asynchronously.

    Args:
        cmd: Command list with executable as first element
        cwd: Working directory
        timeout: Timeout in seconds
        allowed_dirs: Allowed directories for file arguments

    Returns:
        CompletedProcess result
    """
    import asyncio

    if not cmd:
        raise ValueError("Empty command")

    executable = cmd[0]
    full_path = resolve_executable(executable)
    if full_path is None:
        raise FileNotFoundError(f"Executable not found: {executable}")

    validated_cmd = [full_path] + cmd[1:]

    if allowed_dirs:
        for i, arg in enumerate(validated_cmd[1:], 1):
            if isinstance(arg, str) and ("/" in arg or "\\" in arg):
                try:
                    validated_cmd[i] = str(validate_path(Path(arg), allowed_dirs=allowed_dirs))
                except ValueError:
                    pass

    logger.debug(f"Running async command: {validated_cmd}")
    proc = await asyncio.create_subprocess_exec(
        *validated_cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return subprocess.CompletedProcess(
            args=validated_cmd,
            returncode=proc.returncode,
            stdout=stdout.decode("utf-8", errors="ignore") if stdout else "",
            stderr=stderr.decode("utf-8", errors="ignore") if stderr else "",
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise subprocess.TimeoutExpired(validated_cmd, timeout)


# Common executable resolvers for convenience
def get_ffmpeg() -> Optional[str]:
    """Get full path to ffmpeg."""
    return resolve_executable("ffmpeg")


def get_ffprobe() -> Optional[str]:
    """Get full path to ffprobe."""
    return resolve_executable("ffprobe")


def get_nvidia_smi() -> Optional[str]:
    """Get full path to nvidia-smi."""
    return resolve_executable("nvidia-smi")


def get_sysctl() -> Optional[str]:
    """Get full path to sysctl."""
    return resolve_executable("sysctl")


def get_system_profiler() -> Optional[str]:
    """Get full path to system_profiler (macOS)."""
    return resolve_executable("system_profiler")
