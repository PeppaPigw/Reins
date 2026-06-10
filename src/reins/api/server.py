"""Reins aiohttp.web server — assembles routes and starts the API.

Usage:
    python -m reins.api.server [--host 127.0.0.1] [--port 8000] [--state-dir .reins_state]
    python -m reins.api.server --expose-network  # binds to 0.0.0.0

Environment:
    REINS_HOST       — bind host (default: 127.0.0.1)
    REINS_PORT       — bind port (default: 8000)
    REINS_STATE_DIR  — durable state base dir (default: .reins_state)
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from aiohttp import web

from reins.api.command_routes import (
    handle_abort,
    handle_approve,
    handle_reject,
    handle_resume,
    handle_submit_command,
)
from reins.api.control_plane import ControlPlane
from reins.api.middleware import create_api_middlewares
from reins.api.routes import (
    handle_create_run,
    handle_get_run,
    handle_get_timeline,
)
from reins.api.registry import RunRegistry

log = logging.getLogger("reins.api")


def build_app(state_dir: Path | None = None) -> web.Application:
    """Construct and return the aiohttp Application."""
    control_plane = ControlPlane(state_dir=state_dir)
    app = web.Application(middlewares=create_api_middlewares(control_plane.policy_engine))
    registry = RunRegistry(base_dir=state_dir)
    app["registry"] = registry
    app["control_plane"] = control_plane
    app["metrics"] = control_plane.metrics
    app["event_stream"] = control_plane.stream

    app.router.add_post("/runs", handle_create_run)
    app.router.add_get("/runs/{id}", handle_get_run)
    app.router.add_get("/runs/{id}/timeline", handle_get_timeline)
    app.router.add_post("/runs/{id}/commands", handle_submit_command)
    app.router.add_post("/runs/{id}/approve", handle_approve)
    app.router.add_post("/runs/{id}/reject", handle_reject)
    app.router.add_post("/runs/{id}/abort", handle_abort)
    app.router.add_post("/runs/{id}/resume", handle_resume)
    control_plane.add_routes(app)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    parser = argparse.ArgumentParser(description="Reins agent kernel HTTP API")
    parser.add_argument("--host", default=os.getenv("REINS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("REINS_PORT", "8000")))
    parser.add_argument(
        "--state-dir",
        default=os.getenv("REINS_STATE_DIR", ".reins_state"),
        help="Base directory for durable state (journals, snapshots, checkpoints)",
    )
    parser.add_argument(
        "--expose-network",
        action="store_true",
        default=False,
        help="Bind to 0.0.0.0 instead of localhost (exposes API to network)",
    )
    args = parser.parse_args()

    host = "0.0.0.0" if args.expose_network else args.host
    state_dir = Path(args.state_dir).resolve()
    log.info("Reins API starting on %s:%d (state=%s)", host, args.port, state_dir)

    app = build_app(state_dir=state_dir)
    web.run_app(app, host=host, port=args.port)


if __name__ == "__main__":
    main()
