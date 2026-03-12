"""Security boundary tests for the agent execution sandbox.

Validates that the sandbox correctly blocks dangerous imports, builtins,
and enforces resource limits (memory, CPU/timeout).
"""

from __future__ import annotations

import pytest

from app.agents.sandbox import ExecutionSandbox, SandboxConfig, SandboxResult

# ── Helpers ────────────────────────────────────────────────────────────

_FAST_CONFIG = SandboxConfig(timeout_seconds=10)
_RESOURCE_CONFIG = SandboxConfig(timeout_seconds=5, memory_mb=64, cpu_seconds=2)


def _assert_blocked(result: SandboxResult, module_name: str) -> None:
    """Assert that a sandbox execution was blocked with an ImportError."""
    assert result.success is False, f"Expected {module_name!r} to be blocked"
    combined = (result.stderr or "") + (result.error or "")
    assert "ImportError" in combined or "not allowed" in combined, (
        f"Expected ImportError for {module_name!r}, got: {combined}"
    )


# ── Blocked imports ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_import_os():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python("import os\nprint(os.getcwd())")
    _assert_blocked(result, "os")


@pytest.mark.asyncio
async def test_blocked_import_subprocess():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python("import subprocess\nsubprocess.run(['ls'])")
    _assert_blocked(result, "subprocess")


@pytest.mark.asyncio
async def test_blocked_import_socket():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python("import socket\nsocket.socket()")
    _assert_blocked(result, "socket")


@pytest.mark.asyncio
async def test_blocked_import_pathlib():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python("import pathlib\nprint(pathlib.Path('.'))")
    _assert_blocked(result, "pathlib")


@pytest.mark.asyncio
async def test_blocked_import_pwd():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python("import pwd\nprint(pwd.getpwall())")
    _assert_blocked(result, "pwd")


@pytest.mark.asyncio
async def test_blocked_import_ssl():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python("import ssl\nprint(ssl.OPENSSL_VERSION)")
    _assert_blocked(result, "ssl")


# ── Allowed imports ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allowed_import_math():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python("import math\nprint(math.pi)")
    assert result.success is True, f"math should be allowed: {result.error}"
    assert "3.14159" in result.stdout


@pytest.mark.asyncio
async def test_allowed_import_json():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python('import json\nprint(json.dumps({"a": 1}))')
    assert result.success is True, f"json should be allowed: {result.error}"
    assert '"a"' in result.stdout


@pytest.mark.asyncio
async def test_allowed_import_datetime():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python(
        "import datetime\nprint(datetime.date.today())"
    )
    assert result.success is True, f"datetime should be allowed: {result.error}"
    # Output should be an ISO-format date (e.g. 2026-03-11)
    assert len(result.stdout.strip()) == 10


# ── Blocked builtins ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_builtin_eval():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python('x = eval("1+1")\nprint(x)')
    assert result.success is False, "eval() should be blocked"


@pytest.mark.asyncio
async def test_blocked_builtin_exec_call():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    # The sandbox removes the exec builtin from user code's namespace
    result = await sandbox.execute_python('exec("x=1")\nprint(x)')
    assert result.success is False, "the exec builtin should be blocked"


@pytest.mark.asyncio
async def test_blocked_builtin_open():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python('f = open("/etc/passwd")\nprint(f.read())')
    assert result.success is False, "open() should be blocked"


@pytest.mark.asyncio
async def test_blocked_builtin_globals():
    sandbox = ExecutionSandbox(_FAST_CONFIG)
    result = await sandbox.execute_python("g = globals()\nprint(g)")
    assert result.success is False, "globals() should be blocked"


# ── Resource limits ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resource_limit_memory():
    """Allocating a huge list should be killed by the memory limit or raise MemoryError."""
    sandbox = ExecutionSandbox(_RESOURCE_CONFIG)
    code = "x = [0] * (10 ** 9)\nprint('should not reach here')"
    result = await sandbox.execute_python(code)
    assert result.success is False, "Huge allocation should fail"
    # Accept either a non-zero exit code or an error message
    assert result.exit_code != 0 or result.error, (
        "Expected non-zero exit or error for memory limit"
    )


@pytest.mark.asyncio
async def test_resource_limit_cpu():
    """A tight infinite loop should be stopped by CPU/timeout limits."""
    sandbox = ExecutionSandbox(_RESOURCE_CONFIG)
    code = "while True:\n    pass"
    result = await sandbox.execute_python(code)
    assert result.success is False, "Infinite loop should be stopped"
    assert result.exit_code != 0 or result.error, (
        "Expected non-zero exit or error for CPU limit"
    )
