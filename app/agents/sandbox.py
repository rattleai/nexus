"""Sandboxed code execution for AI agents.

Provides OS-level isolation for agents that need to run generated code.
Uses subprocess with resource limits (rlimit) and restricted builtins for
defense-in-depth. Designed for upgrade path to gVisor/Kata containers
in Kubernetes environments.

Security model:
    - Each execution runs in a subprocess with restricted resources
    - Separate temporary working directory (cleaned after execution)
    - CPU and memory limits enforced via resource.setrlimit
    - Restricted builtins: dangerous functions removed (exec, eval, compile,
      __import__ replaced with allowlist-based importer)
    - File paths passed via environment variables (not string interpolation)
    - Process fork/spawn blocked via RLIMIT_NPROC
    - File creation size limited via RLIMIT_FSIZE
    - No access to parent process environment variables
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.stdlib.get_logger()

# Modules that are always safe to import in the sandbox
_DEFAULT_ALLOWED_IMPORTS = frozenset({
    "math", "random", "string", "re", "json", "csv",
    "datetime", "time", "collections", "itertools", "functools",
    "operator", "decimal", "fractions", "statistics",
    "hashlib", "hmac", "base64", "binascii",
    "textwrap", "difflib", "unicodedata",
    "copy", "pprint", "dataclasses", "typing",
    "io", "enum", "abc", "contextlib",
})

_BLOCKED_IMPORTS = frozenset({
    "os", "sys", "subprocess", "shutil", "signal", "ctypes",
    "importlib", "code", "codeop", "compileall",
    "socket", "http", "urllib", "requests", "httpx",
    "multiprocessing", "threading", "concurrent",
    "pickle", "shelve", "marshal",
    "pathlib",
    "builtins", "__builtin__",
    "pty", "termios", "fcntl",
    "pwd", "grp",
    "ssl", "secrets",
    "webbrowser",
    "tempfile", "glob",
    "sysconfig", "site",
})


@dataclass
class SandboxConfig:
    """Configuration for a sandbox execution environment."""

    memory_mb: int = 256
    cpu_seconds: int = 30
    timeout_seconds: int = 60
    max_output_bytes: int = 1_048_576  # 1 MB
    network_enabled: bool = False
    allowed_imports: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    """Result of a sandboxed code execution."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    return_value: Any = None
    exit_code: int = 0
    duration_ms: int = 0
    memory_used_mb: float = 0.0
    error: str | None = None


class ExecutionSandbox:
    """Subprocess-based code execution sandbox with resource limits.

    Each execution:
    1. Creates a temporary directory
    2. Writes the code to a file in that directory
    3. Spawns a subprocess with rlimits (memory, CPU)
    4. Captures stdout/stderr with size limits
    5. Cleans up the temporary directory
    """

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()

    async def execute_python(
        self,
        code: str,
        *,
        input_data: dict[str, Any] | None = None,
        execution_id: str | None = None,
    ) -> SandboxResult:
        """Execute Python code in an isolated subprocess.

        Args:
            code: Python source code to execute.
            input_data: JSON-serializable data passed via file (not env var).
            execution_id: Tracking ID for logging.
        """
        execution_id = execution_id or uuid.uuid4().hex[:12]
        sandbox_dir = None

        try:
            # Create isolated temp directory
            sandbox_dir = tempfile.mkdtemp(prefix="agent_sandbox_")

            # Write code to file
            code_file = os.path.join(sandbox_dir, "agent_code.py")
            with open(code_file, "w") as f:
                f.write(code)

            # Write input data to file (not env var — avoids size/encoding issues)
            if input_data:
                input_file = os.path.join(sandbox_dir, "input.json")
                with open(input_file, "w") as f:
                    json.dump(input_data, f, default=str)

            # Write wrapper script
            wrapper_code = self._build_wrapper()
            wrapper_file = os.path.join(sandbox_dir, "wrapper.py")
            with open(wrapper_file, "w") as f:
                f.write(wrapper_code)

            # Minimal, clean environment — no host env var leakage
            env = {
                "HOME": sandbox_dir,
                "TMPDIR": sandbox_dir,
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": "",
                "PYTHONDONTWRITEBYTECODE": "1",
                "SANDBOX_DIR": sandbox_dir,
                "SANDBOX_CODE_FILE": code_file,
                "SANDBOX_MEM_BYTES": str(self.config.memory_mb * 1024 * 1024),
                "SANDBOX_CPU_SECONDS": str(self.config.cpu_seconds),
            }

            # Build allowed imports list
            allowed = set(_DEFAULT_ALLOWED_IMPORTS)
            if self.config.allowed_imports:
                allowed.update(self.config.allowed_imports)
            env["SANDBOX_ALLOWED_IMPORTS"] = ",".join(sorted(allowed))
            env["SANDBOX_BLOCKED_IMPORTS"] = ",".join(sorted(_BLOCKED_IMPORTS))

            import time
            start = time.monotonic()

            process = await asyncio.create_subprocess_exec(
                "python3", wrapper_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=sandbox_dir,
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                # Graceful shutdown: SIGTERM first, then SIGKILL
                try:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                except ProcessLookupError:
                    pass  # Process already exited

                return SandboxResult(
                    success=False,
                    error=f"Execution timed out after {self.config.timeout_seconds}s",
                    exit_code=-1,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            duration_ms = int((time.monotonic() - start) * 1000)

            # Truncate output to prevent memory exhaustion
            stdout = stdout_bytes[:self.config.max_output_bytes].decode("utf-8", errors="replace")
            stderr = stderr_bytes[:self.config.max_output_bytes].decode("utf-8", errors="replace")

            # Read result file if it exists
            return_value = None
            if process.returncode == 0:
                result_file = os.path.join(sandbox_dir, "result.json")
                if os.path.exists(result_file):
                    # Limit result file size
                    stat = os.stat(result_file)
                    if stat.st_size <= self.config.max_output_bytes:
                        with open(result_file) as f:
                            try:
                                return_value = json.load(f)
                            except json.JSONDecodeError:
                                pass

            return SandboxResult(
                success=process.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                return_value=return_value,
                exit_code=process.returncode or 0,
                duration_ms=duration_ms,
                error=stderr if process.returncode != 0 else None,
            )

        except Exception as exc:
            logger.error(
                "sandbox_execution_error",
                execution_id=execution_id,
                error=str(exc),
                exc_info=True,
            )
            return SandboxResult(
                success=False,
                error=f"Sandbox setup failed: {exc}",
                exit_code=-2,
            )
        finally:
            if sandbox_dir and os.path.exists(sandbox_dir):
                shutil.rmtree(sandbox_dir, ignore_errors=True)

    def _build_wrapper(self) -> str:
        """Build a Python wrapper that sets resource limits and restricted builtins.

        All paths and configuration come from environment variables, not
        string interpolation, to prevent code injection.
        """
        return '''
import resource
import sys
import os
import json

# ── Resource limits ────────────────────────────────────────────────────
mem_bytes = int(os.environ.get("SANDBOX_MEM_BYTES", "268435456"))
cpu_seconds = int(os.environ.get("SANDBOX_CPU_SECONDS", "30"))

try:
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
except (ValueError, resource.error):
    pass
try:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
except (ValueError, resource.error):
    pass
try:
    resource.setrlimit(resource.RLIMIT_FSIZE, (10485760, 10485760))
except (ValueError, resource.error):
    pass
try:
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
except (ValueError, resource.error):
    pass
try:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except (ValueError, resource.error):
    pass
try:
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
except (ValueError, resource.error):
    pass

# ── Import restriction ─────────────────────────────────────────────────
_allowed_imports = set(os.environ.get("SANDBOX_ALLOWED_IMPORTS", "").split(","))
_blocked_imports = set(os.environ.get("SANDBOX_BLOCKED_IMPORTS", "").split(","))
_original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

def _restricted_import(name, *args, **kwargs):
    top_level = name.split(".")[0]
    if top_level in _blocked_imports:
        raise ImportError(f"Import of '{name}' is not allowed in sandbox")
    if _allowed_imports and top_level not in _allowed_imports:
        raise ImportError(f"Import of '{name}' is not allowed in sandbox")
    return _original_import(name, *args, **kwargs)

# ── Restricted builtins ────────────────────────────────────────────────
_safe_builtins = {}
_dangerous = {"exec", "eval", "compile", "__import__", "globals", "locals",
              "breakpoint", "exit", "quit", "help", "input", "open",
              "memoryview", "credits", "license", "copyright"}
for name in dir(__builtins__):
    if name not in _dangerous:
        _safe_builtins[name] = getattr(__builtins__, name)

# Re-add safe versions
_safe_builtins["__import__"] = _restricted_import
_safe_builtins["print"] = print
_safe_builtins["range"] = range
_safe_builtins["len"] = len
_safe_builtins["type"] = type
_safe_builtins["isinstance"] = isinstance

# ── Load input data ────────────────────────────────────────────────────
sandbox_dir = os.environ.get("SANDBOX_DIR", "")
code_file = os.environ.get("SANDBOX_CODE_FILE", "")
input_data = None
input_path = os.path.join(sandbox_dir, "input.json")
if os.path.exists(input_path):
    with open(input_path) as f:
        input_data = json.load(f)

# ── Execute agent code ─────────────────────────────────────────────────
try:
    with open(code_file) as f:
        code = f.read()
    exec_globals = {"__builtins__": _safe_builtins, "input_data": input_data}
    compiled = compile(code, "<agent_code>", "exec")
    exec(compiled, exec_globals)

    if "result" in exec_globals:
        result_path = os.path.join(sandbox_dir, "result.json")
        with open(result_path, "w") as f:
            json.dump(exec_globals["result"], f, default=str)

except MemoryError:
    print("ERROR: Memory limit exceeded", file=sys.stderr)
    sys.exit(137)
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)
'''
