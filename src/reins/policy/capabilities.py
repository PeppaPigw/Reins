CAPABILITY_RISK_TIERS: dict[str, int] = {
    # T0 — read-only local inspection (fast path eligible)
    "fs.read": 0,
    "search.read": 0,
    "git.status": 0,
    "skill.catalog.lookup": 0,
    "mcp.resource.read": 0,
    "mcp.prompt.get": 0,
    "a2a.agent.discover": 0,
    "db.read": 0,
    # T1 — local workspace writes, sandboxed execution
    "fs.write.workspace": 1,
    "exec.shell.sandboxed": 1,
    "test.run": 1,
    "git.commit": 1,
    # T2 — networked reads, package installs, external issue comments
    "exec.shell.network": 2,
    "mcp.tool.invoke": 2,
    "browser.navigate": 2,
    # T3 — remote writes, pushes, staging deploys, DB writes, browser submits
    "git.push": 3,
    "a2a.agent.call": 3,
    "deploy.staging": 3,
    "db.write": 3,
    "browser.click": 3,
    "browser.submit.external": 3,
    "ticket.write": 3,
    # T4 — prod deploys, financial/identity, irreversible external effects
    "deploy.prod": 4,
    "db.drop": 4,
}
