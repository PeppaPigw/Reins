"""JSON-RPC transport layer for MCP protocol.

Supports both HTTP and stdio transports for communicating with MCP servers.
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class JsonRpcRequest:
    """JSON-RPC 2.0 request."""
    jsonrpc: str = "2.0"
    method: str = ""
    params: dict | list | None = None
    id: int | str | None = None

    def to_dict(self) -> dict:
        result = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.params is not None:
            result["params"] = self.params
        if self.id is not None:
            result["id"] = self.id
        return result


@dataclass
class JsonRpcResponse:
    """JSON-RPC 2.0 response."""
    jsonrpc: str
    id: int | str | None
    result: Any | None = None
    error: dict | None = None

    @classmethod
    def from_dict(cls, data: dict) -> JsonRpcResponse:
        return cls(
            jsonrpc=data.get("jsonrpc", "2.0"),
            id=data.get("id"),
            result=data.get("result"),
            error=data.get("error"),
        )

    def is_error(self) -> bool:
        return self.error is not None


class JsonRpcTransport(ABC):
    """Abstract base for JSON-RPC transports."""

    @abstractmethod
    async def send(self, request: JsonRpcRequest) -> JsonRpcResponse:
        """Send a JSON-RPC request and return the response."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the transport connection."""
        pass


class HttpTransport(JsonRpcTransport):
    """HTTP-based JSON-RPC transport."""

    def __init__(self, endpoint: str, timeout: float = 30.0) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def send(self, request: JsonRpcRequest) -> JsonRpcResponse:
        client = await self._ensure_client()
        try:
            response = await client.post(
                self.endpoint,
                json=request.to_dict(),
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            return JsonRpcResponse.from_dict(data)
        except httpx.HTTPStatusError as e:
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                error={
                    "code": e.response.status_code,
                    "message": f"HTTP error: {e.response.status_code}",
                    "data": str(e),
                },
            )
        except httpx.RequestError as e:
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                error={
                    "code": -32000,
                    "message": "Transport error",
                    "data": str(e),
                },
            )
        except json.JSONDecodeError as e:
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                error={
                    "code": -32700,
                    "message": "Parse error",
                    "data": str(e),
                },
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class StdioTransport(JsonRpcTransport):
    """Stdio-based JSON-RPC transport for subprocess communication."""

    def __init__(self, command: list[str]) -> None:
        self.command = command
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0

    async def _ensure_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        return self._process

    async def send(self, request: JsonRpcRequest) -> JsonRpcResponse:
        process = await self._ensure_process()

        if process.stdin is None or process.stdout is None:
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                error={
                    "code": -32000,
                    "message": "Process stdin/stdout not available",
                },
            )

        try:
            # Send request
            request_data = json.dumps(request.to_dict()) + "\n"
            process.stdin.write(request_data.encode())
            await process.stdin.drain()

            # Read response
            response_line = await process.stdout.readline()
            if not response_line:
                return JsonRpcResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    error={
                        "code": -32000,
                        "message": "No response from process",
                    },
                )

            data = json.loads(response_line.decode())
            return JsonRpcResponse.from_dict(data)

        except json.JSONDecodeError as e:
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                error={
                    "code": -32700,
                    "message": "Parse error",
                    "data": str(e),
                },
            )
        except Exception as e:
            return JsonRpcResponse(
                jsonrpc="2.0",
                id=request.id,
                error={
                    "code": -32000,
                    "message": "Transport error",
                    "data": str(e),
                },
            )

    async def close(self) -> None:
        if self._process is not None:
            if self._process.stdin:
                self._process.stdin.close()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            self._process = None


def create_transport(endpoint: str) -> JsonRpcTransport:
    """Factory function to create appropriate transport based on endpoint."""
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return HttpTransport(endpoint)
    elif endpoint.startswith("stdio://"):
        # Format: stdio://path/to/command or stdio://command with args
        command_str = endpoint.removeprefix("stdio://")
        command = command_str.split()
        return StdioTransport(command)
    else:
        raise ValueError(f"Unsupported endpoint format: {endpoint}")
