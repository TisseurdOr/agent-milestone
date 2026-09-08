"""MCP server exposing git-style version control over agent task trajectories."""
from mcp.server.mcpserver import MCPServer

from store import DEFAULT_DB_PATH, TrailStore

store = TrailStore(DEFAULT_DB_PATH)
mcp = MCPServer("agent-milestone")


@mcp.tool()
def checkpoint(name: str, steps: list[dict]) -> str:
    """Save the current task trajectory under a named milestone (like a git commit)."""
    tip = store.checkpoint(name, steps)
    return f"checkpoint '{name}' -> {tip[:12]}"


@mcp.tool()
def checkout(name: str) -> list[dict]:
    """Return the trajectory recorded at milestone `name` (rollback / recall)."""
    return store.checkout(name)


@mcp.tool()
def export(name: str) -> str:
    """Render milestone `name` as markdown, ready to commit to GitHub."""
    return store.export(name)


if __name__ == "__main__":
    mcp.run()
