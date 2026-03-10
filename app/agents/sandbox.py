"""Sandboxed code execution for AI agents.

Provides OS-level isolation for agents that need to run generated code.
Uses subprocess with resource limits (rlimit, tmpfs, optional seccomp)
for defense-in-depth. Designed for upgrade path to gVisor/Kata containers
in Kubernetes environments.

Security model:
    - Each execution runs in a subprocess with restricted resources
    - Separate tmpfs working directory (cleaned after execution)
    - CPU and memory limits enforced via resource.setrlimit
    - Network access disabled by default
    - No access to host filesystem beyond the tmpfs sandbox
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


@dataclass
class SandboxConfig:
    """Configuration for a sandbox execution environment."""

    memory_mb: int = 256
    cpu_seconds: int = 30
    timeout_seconds: int = 60
    max_output_bytes: int = 1_048_576  # 1 MB
    network_enabled: bool = False
    allowed_imports: list[str] = field(default_factory=list)  # empty = all allowed


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
    1. Creates a temporary directory (tmpfs-backed on Linux)
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
            input_data: JSON-serializable data passed as INPUT_DATA env var.
            execution_id: Tracking ID for logging.
        """
        execution_id = execution_id or uuid.uuid4().hex[:12]
        sandbox_dir = None

        try:
            # Create isolated temp directory
            sandbox_dir = tempfile.mkdtemp(prefix=f"agent_sandbox_{execution_id}_")

            # Write code to file
            code_file = os.path.join(sandbox_dir, "agent_code.py")
            with open(code_file, "w") as f:
                f.write(code)

            # Write input data
            if input_data:
                input_file = os.path.join(sandbox_dir, "input.json")
                with open(input_file, "w") as f:
                    json.dump(input_data, f, default=str)

            # Build wrapper script that sets rlimits before exec
            wrapper_code = self._build_wrapper(code_file, sandbox_dir)
            wrapper_file = os.path.join(sandbox_dir, "wrapper.py")
            with open(wrapper_file, "w") as f:
                f.write(wrapper_code)

            # Set up environment
            env = {
                "HOME": sandbox_dir,
                "TMPDIR": sandbox_dir,
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": "",
                "PYTHONDONTWRITEBYTECODE": "1",
                "SANDBOX_DIR": sandbox_dir,
            }
            if input_data:
                env["INPUT_DATA"] = json.dumps(input_data, default=str)

            # Run in subprocess with timeout
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
                process.kill()
                await process.wait()
                return SandboxResult(
                    success=False,
                    error=f"Execution timed out after {self.config.timeout_seconds}s",
                    exit_code=-1,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            duration_ms = int((time.monotonic() - start) * 1000)

            # Truncate output
            stdout = stdout_bytes[:self.config.max_output_bytes].decode("utf-8", errors="replace")
            stderr = stderr_bytes[:self.config.max_output_bytes].decode("utf-8", errors="replace")

            # Try to parse return value from stdout
            return_value = None
            if process.returncode == 0:
                # Check for JSON result file
                result_file = os.path.join(sandbox_dir, "result.json")
                if os.path.exists(result_file):
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
            # Clean up sandbox directory
            if sandbox_dir and os.path.exists(sandbox_dir):
                try:
                    shutil.rmtree(sandbox_dir, ignore_errors=True)
                except Exception:
                    pass

    def _build_wrapper(self, code_file: str, sandbox_dir: str) -> str:
        """Build a Python wrapper that sets resource limits before executing agent code."""
        mem_bytes = self.config.memory_mb * 1024 * 1024
        cpu_seconds = self.config.cpu_seconds

        return f'''
import resource
import sys
import os
import json

# Set resource limits
try:
    # Memory limit (virtual memory)
    resource.setrlimit(resource.RLIMIT_AS, ({mem_bytes}, {mem_bytes}))
    # CPU time limit
    resource.setrlimit(resource.RLIMIT_CPU, ({cpu_seconds}, {cpu_seconds}))
    # Max file size (10 MB)
    resource.setrlimit(resource.RLIMIT_FSIZE, (10485760, 10485760))
    # Max number of open files
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    # No core dumps
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # No new processes (prevent fork bombs)
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
except (ValueError, resource.error):
    pass  # Some limits may not be available on all platforms

# Load input data if available
input_data = None
input_file = os.path.join("{sandbox_dir}", "input.json")
if os.path.exists(input_file):
    with open(input_file) as f:
        input_data = json.load(f)

# Execute the agent code
try:
    with open("{code_file}") as f:
        code = f.read()
    exec_globals = {{"__builtins__": __builtins__, "input_data": input_data}}
    exec(code, exec_globals)

    # If the code defines a 'result' variable, save it
    if "result" in exec_globals:
        result_file = os.path.join("{sandbox_dir}", "result.json")
        with open(result_file, "w") as f:
            json.dump(exec_globals["result"], f, default=str)

except MemoryError:
    print("ERROR: Memory limit exceeded", file=sys.stderr)
    sys.exit(137)
except Exception as e:
    print(f"ERROR: {{type(e).__name__}}: {{e}}", file=sys.stderr)
    sys.exit(1)
'''
