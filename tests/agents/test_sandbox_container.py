"""Tests for the container-based sandbox (nsjail) routing and command building.

Covers:
    - nsjail availability detection
    - ContainerSandboxRouter backend resolution (auto, nsjail, subprocess, unknown)
    - NsjailSandbox command building: isolation flags, resource limits, security
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.sandbox import SandboxConfig
from app.agents.sandbox_container import (
    ContainerSandboxRouter,
    NsjailSandbox,
    _nsjail_available,
)


# ── TestNsjailAvailability ────────────────────────────────────────────


class TestNsjailAvailability:
    """nsjail binary availability detection."""

    def test_available_when_installed(self):
        with patch("app.agents.sandbox_container.shutil.which", return_value="/usr/bin/nsjail"):
            assert _nsjail_available() is True

    def test_unavailable_when_missing(self):
        with patch("app.agents.sandbox_container.shutil.which", return_value=None):
            assert _nsjail_available() is False


# ── TestContainerSandboxRouter ────────────────────────────────────────


class TestContainerSandboxRouter:
    """Backend resolution logic for the sandbox router."""

    def test_auto_nsjail_when_available(self):
        with (
            patch("app.agents.sandbox_container.settings") as mock_settings,
            patch("app.agents.sandbox_container._nsjail_available", return_value=True),
        ):
            mock_settings.AGENT_SANDBOX_BACKEND = "auto"
            mock_settings.AGENT_SANDBOX_STRICT = False
            router = ContainerSandboxRouter()
        assert router.backend == "nsjail"

    def test_auto_subprocess_fallback(self):
        with (
            patch("app.agents.sandbox_container.settings") as mock_settings,
            patch("app.agents.sandbox_container._nsjail_available", return_value=False),
        ):
            mock_settings.AGENT_SANDBOX_BACKEND = "auto"
            mock_settings.AGENT_SANDBOX_STRICT = False
            router = ContainerSandboxRouter()
        assert router.backend == "subprocess"

    def test_nsjail_strict_raises(self):
        with (
            patch("app.agents.sandbox_container.settings") as mock_settings,
            patch("app.agents.sandbox_container._nsjail_available", return_value=False),
        ):
            mock_settings.AGENT_SANDBOX_BACKEND = "nsjail"
            mock_settings.AGENT_SANDBOX_STRICT = True
            with pytest.raises(RuntimeError, match="nsjail is not available"):
                ContainerSandboxRouter()

    def test_nsjail_nonstrict_fallback(self):
        with (
            patch("app.agents.sandbox_container.settings") as mock_settings,
            patch("app.agents.sandbox_container._nsjail_available", return_value=False),
        ):
            mock_settings.AGENT_SANDBOX_BACKEND = "nsjail"
            mock_settings.AGENT_SANDBOX_STRICT = False
            router = ContainerSandboxRouter()
        assert router.backend == "subprocess"

    def test_subprocess_always_works(self):
        with (
            patch("app.agents.sandbox_container.settings") as mock_settings,
            patch("app.agents.sandbox_container._nsjail_available", return_value=False),
        ):
            mock_settings.AGENT_SANDBOX_BACKEND = "subprocess"
            mock_settings.AGENT_SANDBOX_STRICT = False
            router = ContainerSandboxRouter()
        assert router.backend == "subprocess"

    def test_unknown_falls_back(self):
        with (
            patch("app.agents.sandbox_container.settings") as mock_settings,
            patch("app.agents.sandbox_container._nsjail_available", return_value=False),
        ):
            mock_settings.AGENT_SANDBOX_BACKEND = "invalid"
            mock_settings.AGENT_SANDBOX_STRICT = False
            router = ContainerSandboxRouter()
        assert router.backend == "subprocess"


# ── TestNsjailCommandBuilding ─────────────────────────────────────────


class TestNsjailCommandBuilding:
    """Nsjail command construction: flags, resource limits, security hardening."""

    def _build_cmd(self, config=None, network_enabled=None):
        cfg = config or SandboxConfig()
        if network_enabled is not None:
            cfg.network_enabled = network_enabled
        sandbox = NsjailSandbox(cfg)
        return sandbox._build_nsjail_command(
            sandbox_dir="/tmp/test_sandbox",
            wrapper_file="/tmp/test_sandbox/wrapper.py",
        )

    def test_command_is_list(self):
        cmd = self._build_cmd()
        assert isinstance(cmd, list), "Command must be a list, not a string (prevents shell injection)"
        assert all(isinstance(arg, str) for arg in cmd)

    def test_memory_limits_included(self):
        config = SandboxConfig(memory_mb=512)
        cmd = self._build_cmd(config=config)
        expected_bytes = str(512 * 1024 * 1024)
        assert "--cgroup_mem_max" in cmd
        idx = cmd.index("--cgroup_mem_max")
        assert cmd[idx + 1] == expected_bytes

    def test_network_disabled(self):
        cmd = self._build_cmd(network_enabled=False)
        assert "--disable_clone_newnet" in cmd

    def test_seccomp_flag(self):
        cmd = self._build_cmd()
        assert "--seccomp_log" in cmd

    def test_mount_flags(self):
        cmd = self._build_cmd()
        assert "--bindmount_ro" in cmd
        # /usr must be mounted read-only
        idx = cmd.index("--bindmount_ro")
        assert cmd[idx + 1] == "/usr"
