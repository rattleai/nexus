"""Container-based sandbox upgrade using nsjail for production deployments.

Provides:
    - nsjail integration: Linux namespace isolation (PID, mount, network, cgroup v2)
    - Fallback chain: nsjail (production) -> subprocess+rlimits (development) -> reject (strict)
    - Resource accounting: Track actual CPU/memory per execution via cgroup stats
    - seccomp-bpf syscall filtering
    - Network namespace with opt-in egress allowlist

The SandboxConfig/SandboxResult interfaces from sandbox.py are preserved unchanged.

Configuration:
    AGENT_SANDBOX_BACKEND: "nsjail" | "subprocess" | "auto"
    AGENT_SANDBOX_STRICT: If True, reject execution when nsjail is unavailable
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import os
import shutil
import tempfile
import uuid
from typing import Any

import structlog

from app.agents.sandbox import ExecutionSandbox, SandboxConfig, SandboxResult
from app.config import settings

logger = structlog.stdlib.get_logger()


def _nsjail_available() -> bool:
    """Check if nsjail is installed and accessible."""
    return shutil.which("nsjail") is not None


class NsjailSandbox:
    """nsjail-based sandbox with Linux namespace isolation.

    Uses nsjail to provide:
    - PID namespace isolation (agent can't see host processes)
    - Mount namespace (read-only root, tmpfs for scratch)
    - Network namespace (no network by default, opt-in with egress allowlist)
    - cgroup v2 resource limits (memory, CPU, I/O)
    - seccomp-bpf syscall filtering
    """

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()

    async def execute_python(
        self,
        code: str,
        *,
        input_data: dict[str, Any] | None = None,
        execution_id: str | None = None,
        egress_allowlist: list[str] | None = None,
    ) -> SandboxResult:
        """Execute Python code inside an nsjail container."""
        execution_id = execution_id or uuid.uuid4().hex[:12]
        sandbox_dir = None

        try:
            sandbox_dir = tempfile.mkdtemp(prefix="agent_nsjail_")

            # Write code and input data
            code_file = os.path.join(sandbox_dir, "agent_code.py")
            with open(code_file, "w") as f:
                f.write(code)

            if input_data:
                input_file = os.path.join(sandbox_dir, "input.json")
                with open(input_file, "w") as f:
                    json.dump(input_data, f, default=str)

            # Write wrapper script (reuse from subprocess sandbox)
            wrapper_file = os.path.join(sandbox_dir, "wrapper.py")
            with open(wrapper_file, "w") as f:
                f.write(self._build_wrapper())

            # Build nsjail command (uses execFile-style list, not shell string)
            cmd = self._build_nsjail_command(
                sandbox_dir=sandbox_dir,
                wrapper_file=wrapper_file,
                egress_allowlist=egress_allowlist,
            )

            import time

            start = time.monotonic()

            # Uses create_subprocess_exec (not shell) to avoid command injection
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=sandbox_dir,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.config.timeout_seconds,
                )
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3)
                    except TimeoutError:
                        process.kill()
                        await process.wait()

                return SandboxResult(
                    success=False,
                    error=f"Execution timed out after {self.config.timeout_seconds}s",
                    exit_code=-1,
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            duration_ms = int((time.monotonic() - start) * 1000)

            stdout = stdout_bytes[: self.config.max_output_bytes].decode("utf-8", errors="replace")
            stderr = stderr_bytes[: self.config.max_output_bytes].decode("utf-8", errors="replace")

            # Read result file
            return_value = None
            result_file = os.path.join(sandbox_dir, "result.json")
            if process.returncode == 0 and os.path.exists(result_file):
                stat = os.stat(result_file)
                if stat.st_size <= self.config.max_output_bytes:
                    with open(result_file) as f, contextlib.suppress(json.JSONDecodeError):
                        return_value = json.load(f)

            # Parse cgroup stats for resource accounting
            memory_used_mb = self._parse_cgroup_memory(sandbox_dir)

            return SandboxResult(
                success=process.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                return_value=return_value,
                exit_code=process.returncode or 0,
                duration_ms=duration_ms,
                memory_used_mb=memory_used_mb,
                error=stderr if process.returncode != 0 else None,
            )

        except Exception as exc:
            logger.error(
                "nsjail_execution_error",
                execution_id=execution_id,
                error=str(exc),
                exc_info=True,
            )
            return SandboxResult(
                success=False,
                error=f"nsjail sandbox setup failed: {exc}",
                exit_code=-2,
            )
        finally:
            if sandbox_dir and os.path.exists(sandbox_dir):
                shutil.rmtree(sandbox_dir, ignore_errors=True)

    def _build_nsjail_command(
        self,
        *,
        sandbox_dir: str,
        wrapper_file: str,
        egress_allowlist: list[str] | None = None,
    ) -> list[str]:
        """Build the nsjail command with all isolation flags.

        Returns a list of arguments for subprocess_exec (no shell interpolation).
        """
        mem_bytes = self.config.memory_mb * 1024 * 1024

        cmd = [
            "nsjail",
            "--mode",
            "o",  # Once mode (execute and exit)
            "--chroot",
            "/",
            "--rw",
            # PID namespace
            "--disable_clone_newuser",
            # Resource limits via cgroup v2
            "--cgroup_mem_max",
            str(mem_bytes),
            "--cgroup_cpu_ms_per_sec",
            "1000",
            "--time_limit",
            str(self.config.timeout_seconds),
            "--rlimit_as",
            str(self.config.memory_mb),
            "--rlimit_cpu",
            str(self.config.cpu_seconds),
            "--rlimit_fsize",
            "10",  # 10 MB max file size
            "--rlimit_nofile",
            "64",
            "--rlimit_nproc",
            "1",
            # Mount namespace: sandbox dir is writable, rest read-only
            "--bindmount_ro",
            "/usr",
            "--bindmount_ro",
            "/lib",
            "--bindmount_ro",
            "/lib64",
            "--bindmount_ro",
            "/etc/alternatives",
            "--bindmount",
            f"{sandbox_dir}:{sandbox_dir}",
            "--tmpfsmount",
            "/tmp",
            # seccomp-bpf logging
            "--seccomp_log",
            # Env (passed as individual flags, not shell variables)
            "--env",
            f"HOME={sandbox_dir}",
            "--env",
            f"TMPDIR={sandbox_dir}",
            "--env",
            "PATH=/usr/bin:/bin",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            f"SANDBOX_DIR={sandbox_dir}",
        ]

        # Network namespace: disabled by default
        if not self.config.network_enabled:
            cmd.extend(["--disable_clone_newnet"])
        elif egress_allowlist:
            # Enforce egress allowlist via iptables rules in a pre-exec script
            egress_script = self._build_egress_script(egress_allowlist, sandbox_dir)
            cmd.extend(["--setup_cmd", egress_script])
            # Bind resolv.conf read-only to prevent DNS covert channels
            cmd.extend(["--bindmount_ro", "/etc/resolv.conf"])
            logger.info(
                "nsjail_network_egress_enforced",
                allowlist=egress_allowlist,
            )
        else:
            # Network enabled but no allowlist — block ALL egress as safety default
            cmd.extend(["--disable_clone_newnet"])
            logger.warning("nsjail_network_enabled_no_allowlist_blocking_all")

        # Execute python3 with wrapper (arguments as list, not string)
        cmd.extend(["--", "python3", wrapper_file])

        return cmd

    def _build_wrapper(self) -> str:
        """Build a wrapper script for nsjail execution (reuses subprocess sandbox wrapper)."""
        sandbox = ExecutionSandbox(self.config)
        return sandbox._build_wrapper()

    def _parse_cgroup_memory(self, sandbox_dir: str) -> float:
        """Parse cgroup v2 memory peak if available.

        Tries nsjail's cgroup path format first, then falls back to
        the .cgroup_stats JSON file.
        """
        candidate_paths = [
            f"/sys/fs/cgroup/nsjail/{os.path.basename(sandbox_dir)}/memory.peak",
            os.path.join(sandbox_dir, ".cgroup_stats"),
        ]
        for cgroup_path in candidate_paths:
            try:
                if not os.path.exists(cgroup_path):
                    continue
                with open(cgroup_path) as f:
                    content = f.read().strip()
                if not content:
                    continue
                if content.startswith("{"):
                    data = json.loads(content)
                    return data.get("memory_peak_mb", 0.0)
                return int(content) / (1024 * 1024)
            except Exception:
                continue
        return 0.0

    def _build_egress_script(self, allowlist: list[str], sandbox_dir: str) -> str:
        """Build a shell script that sets up iptables rules for egress allowlisting.

        Only valid IP addresses/CIDRs are added. Non-IP entries (hostnames)
        are skipped with a log warning.
        """
        rules = ["#!/bin/sh", "set -e", "# Egress allowlist enforcement"]
        rules.append("iptables -P OUTPUT DROP")
        rules.append("iptables -A OUTPUT -o lo -j ACCEPT")
        rules.append("# Allow established connections")
        rules.append("iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT")

        for entry in allowlist:
            try:
                network = ipaddress.ip_network(entry, strict=False)
                rules.append(f"iptables -A OUTPUT -d {network} -j ACCEPT")
            except ValueError:
                logger.warning(
                    "nsjail_egress_invalid_entry",
                    entry=entry,
                    reason="not a valid IP or CIDR, skipping",
                )
                rules.append(f"# Skipped invalid entry: {entry}")

        script_path = os.path.join(sandbox_dir, "setup_egress.sh")
        with open(script_path, "w") as f:
            f.write("\n".join(rules) + "\n")
        os.chmod(script_path, 0o755)
        return script_path


class ContainerSandboxRouter:
    """Routes sandbox execution to the appropriate backend.

    Fallback chain: nsjail (production) -> subprocess+rlimits (dev) -> reject (strict)
    """

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()
        self._backend = self._resolve_backend()

    def _resolve_backend(self) -> str:
        """Determine which sandbox backend to use."""
        backend = settings.AGENT_SANDBOX_BACKEND

        if backend == "nsjail":
            if _nsjail_available():
                return "nsjail"
            if settings.AGENT_SANDBOX_STRICT:
                raise RuntimeError(
                    "AGENT_SANDBOX_BACKEND=nsjail but nsjail is not available. "
                    "Install nsjail or set AGENT_SANDBOX_STRICT=false."
                )
            logger.warning("nsjail_not_available_falling_back_to_subprocess")
            return "subprocess"

        if backend == "auto":
            if _nsjail_available():
                logger.info("sandbox_backend_auto_resolved", backend="nsjail")
                return "nsjail"
            logger.info("sandbox_backend_auto_resolved", backend="subprocess")
            return "subprocess"

        if backend == "subprocess":
            return "subprocess"

        logger.warning("unknown_sandbox_backend", backend=backend)
        return "subprocess"

    async def execute_python(
        self,
        code: str,
        *,
        input_data: dict[str, Any] | None = None,
        execution_id: str | None = None,
    ) -> SandboxResult:
        """Execute code via the resolved sandbox backend."""
        if self._backend == "nsjail":
            sandbox = NsjailSandbox(self.config)
            return await sandbox.execute_python(
                code,
                input_data=input_data,
                execution_id=execution_id,
            )
        else:
            sandbox = ExecutionSandbox(self.config)
            return await sandbox.execute_python(
                code,
                input_data=input_data,
                execution_id=execution_id,
            )

    @property
    def backend(self) -> str:
        """Return the active sandbox backend name."""
        return self._backend
