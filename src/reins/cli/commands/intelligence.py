from __future__ import annotations


import typer

from reins.cli import utils

app = typer.Typer(help="Intelligence layer management.")


@app.command("status")
def intelligence_status() -> None:
    """Show intelligence layer status: trust levels, memory count, patterns."""
    repo_root = utils.find_repo_root()
    config = utils.load_config(repo_root)
    intel_config = config.intelligence

    if not intel_config.enabled:
        utils.console.print("[dim]Intelligence layer is disabled.[/dim]")
        utils.console.print("Enable with: intelligence.enabled = true in .reins/config.yaml")
        return

    store_path = repo_root / intel_config.store_path

    from reins.intelligence.memory.engine import MemoryEngine
    from reins.intelligence.strategy.trust import TrustModel

    memory = MemoryEngine(store_path / "memory")
    trust = TrustModel(store_path / "trust")

    rows = [
        {"field": "enabled", "value": str(intel_config.enabled)},
        {"field": "mode", "value": intel_config.mode},
        {"field": "store_path", "value": intel_config.store_path},
        {"field": "memory_records", "value": str(memory.record_count)},
        {"field": "known_domains", "value": ", ".join(trust.known_domains) or "-"},
    ]

    for domain in trust.known_domains:
        score = trust.get_domain_trust(domain)
        rows.append({
            "field": f"trust:{domain}",
            "value": f"{score.level.value} (score={score.score:.2f})",
        })

    utils.console.print(utils.format_table(rows, ["field", "value"]))


@app.command("trust")
def intelligence_trust(
    domain: str = typer.Argument(None, help="Domain to inspect (or all if omitted)."),
) -> None:
    """Show trust scores for domains."""
    repo_root = utils.find_repo_root()
    config = utils.load_config(repo_root)
    store_path = repo_root / config.intelligence.store_path

    from reins.intelligence.strategy.trust import TrustModel

    trust = TrustModel(store_path / "trust")

    if domain:
        score = trust.get_domain_trust(domain)
        rows = [
            {"field": "domain", "value": score.domain},
            {"field": "level", "value": score.level.value},
            {"field": "score", "value": f"{score.score:.4f}"},
            {"field": "effective_successes", "value": f"{score.effective_successes:.2f}"},
            {"field": "effective_failures", "value": f"{score.effective_failures:.2f}"},
            {"field": "last_updated", "value": score.last_updated},
        ]
        utils.console.print(utils.format_table(rows, ["field", "value"]))
    else:
        domains = trust.known_domains
        if not domains:
            utils.console.print("[dim]No trust data yet.[/dim]")
            return
        rows = []
        for d in sorted(domains):
            s = trust.get_domain_trust(d)
            rows.append({
                "domain": d,
                "level": s.level.value,
                "score": f"{s.score:.3f}",
                "successes": f"{s.effective_successes:.1f}",
                "failures": f"{s.effective_failures:.1f}",
            })
        utils.console.print(
            utils.format_table(rows, ["domain", "level", "score", "successes", "failures"])
        )


@app.command("memory")
def intelligence_memory(
    query: str = typer.Argument(None, help="Search query for memories."),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results."),
) -> None:
    """Query the intelligence memory store."""
    import asyncio

    repo_root = utils.find_repo_root()
    config = utils.load_config(repo_root)
    store_path = repo_root / config.intelligence.store_path

    from reins.intelligence.memory.engine import MemoryEngine
    from reins.intelligence.types import MemoryQuery

    memory = MemoryEngine(store_path / "memory")

    if not query:
        utils.console.print(f"[dim]Memory store: {memory.record_count} records[/dim]")
        return

    results = asyncio.run(memory.query(MemoryQuery(query_text=query, limit=limit)))

    if not results:
        utils.console.print("[dim]No matching memories found.[/dim]")
        return

    rows = []
    for scored in results:
        rows.append({
            "id": scored.record.memory_id[:12],
            "type": scored.record.memory_type.value,
            "relevance": f"{scored.relevance:.3f}",
            "content": scored.record.content[:60],
        })
    utils.console.print(utils.format_table(rows, ["id", "type", "relevance", "content"]))


@app.command("reset")
def intelligence_reset(
    domain: str = typer.Argument(None, help="Domain to reset trust for."),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Reset trust for a domain (or all domains)."""
    import asyncio

    if not confirm:
        target = domain or "ALL domains"
        if not typer.confirm(f"Reset trust for {target}?"):
            raise typer.Abort()

    repo_root = utils.find_repo_root()
    config = utils.load_config(repo_root)
    store_path = repo_root / config.intelligence.store_path

    from reins.intelligence.strategy.trust import TrustModel
    from reins.intelligence.types import TrustLevel

    trust = TrustModel(store_path / "trust")

    if domain:
        asyncio.run(trust.hard_demote(domain, TrustLevel.supervised, "manual reset"))
        utils.console.print(f"Trust reset to supervised for domain: {domain}")
    else:
        for d in trust.known_domains:
            asyncio.run(trust.hard_demote(d, TrustLevel.supervised, "manual reset"))
        utils.console.print("Trust reset to supervised for all domains.")
