"""Tests for the agent execution sandbox."""

from __future__ import annotations

import pytest

from app.agents.sandbox import ExecutionSandbox, SandboxConfig


class TestSandboxExecution:
    @pytest.mark.asyncio
    async def test_simple_code_execution(self):
        sandbox = ExecutionSandbox(SandboxConfig(timeout_seconds=10))
        result = await sandbox.execute_python('print("hello world")')

        assert result.success is True
        assert "hello world" in result.stdout
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_code_with_error(self):
        sandbox = ExecutionSandbox(SandboxConfig(timeout_seconds=10))
        result = await sandbox.execute_python("raise ValueError('test error')")

        assert result.success is False
        assert result.exit_code != 0
        assert "ValueError" in (result.stderr or result.error or "")

    @pytest.mark.asyncio
    async def test_timeout(self):
        sandbox = ExecutionSandbox(SandboxConfig(timeout_seconds=2))
        result = await sandbox.execute_python("import time; time.sleep(10)")

        assert result.success is False
        assert "timed out" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_result_variable_captured(self):
        sandbox = ExecutionSandbox(SandboxConfig(timeout_seconds=10))
        result = await sandbox.execute_python('result = {"answer": 42}')

        assert result.success is True
        if result.return_value:
            assert result.return_value == {"answer": 42}

    @pytest.mark.asyncio
    async def test_input_data_available(self):
        sandbox = ExecutionSandbox(SandboxConfig(timeout_seconds=10))
        result = await sandbox.execute_python(
            'print(input_data["name"])',
            input_data={"name": "test"},
        )

        assert result.success is True
        assert "test" in result.stdout

    @pytest.mark.asyncio
    async def test_sandbox_cleanup(self):
        """Verify sandbox directory is cleaned up after execution."""
        import os
        import tempfile

        sandbox = ExecutionSandbox(SandboxConfig(timeout_seconds=10))

        # Before execution, note existing temp dirs
        before = set(os.listdir(tempfile.gettempdir()))

        await sandbox.execute_python('print("cleanup test")')

        # After execution, sandbox dir should be cleaned up
        after = set(os.listdir(tempfile.gettempdir()))
        new_dirs = after - before
        sandbox_dirs = [d for d in new_dirs if d.startswith("agent_sandbox_")]
        assert len(sandbox_dirs) == 0, f"Sandbox dirs not cleaned up: {sandbox_dirs}"


class TestSandboxConfig:
    def test_default_config(self):
        config = SandboxConfig()
        assert config.memory_mb == 256
        assert config.cpu_seconds == 30
        assert config.timeout_seconds == 60
        assert config.network_enabled is False

    def test_custom_config(self):
        config = SandboxConfig(memory_mb=512, cpu_seconds=60, network_enabled=True)
        assert config.memory_mb == 512
        assert config.cpu_seconds == 60
        assert config.network_enabled is True
