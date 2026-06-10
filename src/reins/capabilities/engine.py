from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from reins.capabilities.types import (
    Capability,
    CapabilityProvider,
    CapabilityRequest,
    CapabilityStatus,
    ComposedCapability,
    CompositionMode,
    InvocationResult,
    NegotiationOutcome,
    NegotiationResult,
)


class CapabilityRegistry:
    """Dynamic capability discovery, negotiation, and composition at runtime.

    Agents register capabilities they provide. Other agents discover and
    invoke those capabilities through negotiation, with support for
    fallback chains, parallel invocation, and best-of selection.
    """

    def __init__(self) -> None:
        self._providers: dict[str, CapabilityProvider] = {}
        self._by_capability: dict[str, list[str]] = defaultdict(list)
        self._compositions: dict[str, ComposedCapability] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._invocations: list[InvocationResult] = []

    @property
    def provider_count(self) -> int:
        return len(self._providers)

    @property
    def capability_names(self) -> list[str]:
        return list(self._by_capability.keys())

    def register_provider(self, provider: CapabilityProvider) -> None:
        self._providers[provider.provider_id] = provider
        for cap in provider.capabilities:
            if provider.provider_id not in self._by_capability[cap.name]:
                self._by_capability[cap.name].append(provider.provider_id)

    def unregister_provider(self, provider_id: str) -> bool:
        provider = self._providers.pop(provider_id, None)
        if not provider:
            return False
        for cap in provider.capabilities:
            pids = self._by_capability.get(cap.name, [])
            if provider_id in pids:
                pids.remove(provider_id)
        return True

    def register_handler(self, capability_name: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._handlers[capability_name] = handler

    def discover(self, capability_name: str, status_filter: CapabilityStatus | None = None) -> list[CapabilityProvider]:
        provider_ids = self._by_capability.get(capability_name, [])
        providers = [self._providers[pid] for pid in provider_ids if pid in self._providers]
        if status_filter:
            providers = [p for p in providers if p.status == status_filter]
        return sorted(providers, key=lambda p: p.priority, reverse=True)

    def negotiate(self, request: CapabilityRequest) -> NegotiationResult:
        providers = self.discover(request.capability_name, CapabilityStatus.AVAILABLE)

        if request.preferred_providers:
            preferred = [p for p in providers if p.agent_id in request.preferred_providers]
            if preferred:
                providers = preferred

        if not providers:
            return NegotiationResult(
                request_id=request.request_id,
                outcome=NegotiationOutcome.DENIED,
                reason=f"No available providers for '{request.capability_name}'",
            )

        for provider in providers:
            cap = self._find_capability(provider, request.capability_name)
            if not cap:
                continue

            if request.max_cost is not None and cap.cost_per_call > request.max_cost:
                continue
            if request.max_latency_ms is not None and cap.avg_latency_ms > request.max_latency_ms:
                continue

            return NegotiationResult(
                request_id=request.request_id,
                outcome=NegotiationOutcome.GRANTED,
                provider_id=provider.provider_id,
                capability_id=cap.capability_id,
                reason=f"Matched provider '{provider.agent_id}'",
            )

        return NegotiationResult(
            request_id=request.request_id,
            outcome=NegotiationOutcome.DENIED,
            reason="No providers meet cost/latency constraints",
        )

    def invoke(self, capability_name: str, input_data: dict[str, Any], provider_id: str | None = None) -> InvocationResult:
        handler = self._handlers.get(capability_name)
        if not handler:
            result = InvocationResult(
                capability_name=capability_name,
                provider_id=provider_id or "unknown",
                success=False,
                error=f"No handler registered for '{capability_name}'",
            )
            self._invocations.append(result)
            return result

        import time
        start = time.perf_counter()
        try:
            output = handler(input_data)
            duration = (time.perf_counter() - start) * 1000
            result = InvocationResult(
                capability_name=capability_name,
                provider_id=provider_id or "local",
                success=True,
                output=output,
                latency_ms=duration,
            )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            result = InvocationResult(
                capability_name=capability_name,
                provider_id=provider_id or "local",
                success=False,
                error=str(e),
                latency_ms=duration,
            )

        self._invocations.append(result)
        return result

    def compose(self, name: str, mode: CompositionMode, capability_names: list[str]) -> ComposedCapability:
        composition = ComposedCapability(
            name=name,
            mode=mode,
            steps=tuple(capability_names),
            fallback_order=tuple(capability_names) if mode == CompositionMode.FALLBACK else (),
        )
        self._compositions[name] = composition
        return composition

    def invoke_composed(self, composition_name: str, input_data: dict[str, Any]) -> list[InvocationResult]:
        composition = self._compositions.get(composition_name)
        if not composition:
            return [InvocationResult(
                capability_name=composition_name,
                provider_id="unknown",
                success=False,
                error=f"Composition '{composition_name}' not found",
            )]

        if composition.mode == CompositionMode.SEQUENTIAL:
            return self._invoke_sequential(composition, input_data)
        elif composition.mode == CompositionMode.PARALLEL:
            return self._invoke_parallel(composition, input_data)
        elif composition.mode == CompositionMode.FALLBACK:
            return self._invoke_fallback(composition, input_data)
        elif composition.mode == CompositionMode.BEST_OF:
            return self._invoke_parallel(composition, input_data)
        return []

    def get_stats(self) -> dict[str, Any]:
        success_count = sum(1 for r in self._invocations if r.success)
        total = len(self._invocations)
        return {
            "total_invocations": total,
            "success_rate": success_count / total if total else 0.0,
            "providers": self.provider_count,
            "capabilities": len(self._by_capability),
            "compositions": len(self._compositions),
        }

    def _find_capability(self, provider: CapabilityProvider, name: str) -> Capability | None:
        for cap in provider.capabilities:
            if cap.name == name:
                return cap
        return None

    def _invoke_sequential(self, composition: ComposedCapability, input_data: dict[str, Any]) -> list[InvocationResult]:
        results = []
        ctx = dict(input_data)
        for cap_name in composition.steps:
            result = self.invoke(cap_name, ctx)
            results.append(result)
            if result.success and result.output is not None:
                if isinstance(result.output, dict):
                    ctx.update(result.output)
                else:
                    ctx[cap_name] = result.output
        return results

    def _invoke_parallel(self, composition: ComposedCapability, input_data: dict[str, Any]) -> list[InvocationResult]:
        return [self.invoke(cap_name, input_data) for cap_name in composition.steps]

    def _invoke_fallback(self, composition: ComposedCapability, input_data: dict[str, Any]) -> list[InvocationResult]:
        results = []
        for cap_name in composition.fallback_order:
            result = self.invoke(cap_name, input_data)
            results.append(result)
            if result.success:
                break
        return results
