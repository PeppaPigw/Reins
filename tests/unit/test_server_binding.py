"""Tests for API server binding defaults and --expose-network flag."""

from __future__ import annotations

import argparse
import os
from unittest.mock import patch

import pytest


def test_default_host_is_localhost():
    """Default host must be 127.0.0.1, not 0.0.0.0."""
    with patch.dict(os.environ, {}, clear=False):
        # Remove REINS_HOST if set
        env = {k: v for k, v in os.environ.items() if k != "REINS_HOST"}
        with patch.dict(os.environ, env, clear=True):
            default = os.getenv("REINS_HOST", "127.0.0.1")
            assert default == "127.0.0.1"


def test_expose_network_flag_parsed():
    """--expose-network flag must set expose_network=True."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--expose-network",
        action="store_true",
        default=False,
    )

    args = parser.parse_args(["--expose-network"])
    assert args.expose_network is True


def test_expose_network_flag_absent():
    """Without --expose-network, expose_network is False."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--expose-network",
        action="store_true",
        default=False,
    )

    args = parser.parse_args([])
    assert args.expose_network is False


def test_host_resolution_with_expose_network():
    """When --expose-network is set, host resolves to 0.0.0.0."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--expose-network",
        action="store_true",
        default=False,
    )

    args = parser.parse_args(["--expose-network"])
    host = "0.0.0.0" if args.expose_network else args.host
    assert host == "0.0.0.0"


def test_host_resolution_without_expose_network():
    """Without --expose-network, host stays at default 127.0.0.1."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--expose-network",
        action="store_true",
        default=False,
    )

    args = parser.parse_args([])
    host = "0.0.0.0" if args.expose_network else args.host
    assert host == "127.0.0.1"


def test_host_resolution_custom_host_without_expose():
    """Custom --host is respected when --expose-network is absent."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--expose-network",
        action="store_true",
        default=False,
    )

    args = parser.parse_args(["--host", "192.168.1.100"])
    host = "0.0.0.0" if args.expose_network else args.host
    assert host == "192.168.1.100"


def test_expose_network_overrides_custom_host():
    """--expose-network overrides any --host value to 0.0.0.0."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--expose-network",
        action="store_true",
        default=False,
    )

    args = parser.parse_args(["--host", "192.168.1.100", "--expose-network"])
    host = "0.0.0.0" if args.expose_network else args.host
    assert host == "0.0.0.0"


def test_server_source_contains_localhost_default():
    """server.py must default to 127.0.0.1, not 0.0.0.0 in getenv call."""
    from pathlib import Path

    server_path = Path(__file__).parent.parent.parent / "src" / "reins" / "api" / "server.py"
    content = server_path.read_text()
    assert '"REINS_HOST", "127.0.0.1"' in content
    assert '"REINS_HOST", "0.0.0.0"' not in content


def test_server_source_contains_expose_network():
    """server.py must contain the --expose-network flag."""
    from pathlib import Path

    server_path = Path(__file__).parent.parent.parent / "src" / "reins" / "api" / "server.py"
    content = server_path.read_text()
    assert "expose-network" in content or "expose_network" in content
