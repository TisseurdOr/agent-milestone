"""MCP server exposing git-style version control over agent task trajectories."""
from mcp.server.mcpserver import MCPServer

from store import DEFAULT_DB_PATH, TrailStore

store = TrailStore(DEFAULT_DB_PATH)
mcp = MCPServer("agent-milestone")


@mcp.tool()
def checkpoint(name: str, steps: list[dict], parent_ref: str | None = None) -> str:
    """Save the current task trajectory under a named milestone (like a git commit).

    ``parent_ref`` optionally groups the milestone under a branch/folder.
    """
    tip = store.checkpoint(name, steps, parent_ref=parent_ref)
    return f"checkpoint '{name}' -> {tip[:12]}"


@mcp.tool()
def checkout(name: str) -> list[dict]:
    """Return the trajectory recorded at milestone/branch `name` (read-only recall)."""
    return store.checkout(name)


@mcp.tool()
def export(name: str) -> str:
    """Render milestone `name` as markdown, ready to commit to GitHub."""
    return store.export(name)


@mcp.tool()
def list_milestones() -> list[dict]:
    """List milestones and branches with tip hash, step count, and timestamps."""
    return store.list_refs()


@mcp.tool()
def branch(name: str, from_ref: str) -> dict:
    """Create a branch ref at another milestone/branch (like git branch)."""
    return store.branch(name, from_ref)


@mcp.tool()
def diff(left: str, right: str) -> dict:
    """Diff two milestones/branches from their fork point."""
    return store.diff(left, right)


@mcp.tool()
def replay(name: str) -> dict:
    """Return a dry-run replay plan for a milestone. Tools are never executed."""
    return store.replay(name, execute=False)


@mcp.tool()
def rename(old_name: str, new_name: str) -> dict:
    """Rename a milestone/branch without touching immutable steps."""
    return store.rename(old_name, new_name)


@mcp.tool()
def delete(name: str) -> dict:
    """Delete a milestone/branch ref (run gc to remove unreachable steps)."""
    return store.delete(name)


@mcp.tool()
def gc(dry_run: bool = True) -> dict:
    """Garbage-collect steps unreachable from any ref. Dry-run by default."""
    return store.gc(dry_run=dry_run)


@mcp.tool()
def prune(older_than_days: int | None = None, keep_last: int | None = None, dry_run: bool = True) -> dict:
    """Prune old refs and optionally garbage-collect unreachable steps."""
    return store.prune(older_than_days=older_than_days, keep_last=keep_last, dry_run=dry_run)


@mcp.tool()
def rollback(name: str, to_ref: str) -> dict:
    """Move a ref back to another ref without deleting immutable steps."""
    return store.rollback(name, to_ref)


@mcp.tool()
def undo_last(name: str) -> dict:
    """Move a ref back to the previous tip recorded in reflog."""
    return store.undo_last(name)


@mcp.tool()
def set_parent(name: str, parent_ref: str | None = None) -> dict:
    """Move a milestone/branch into a branch folder (or back to root)."""
    return store.set_parent(name, parent_ref)


@mcp.tool()
def reflog(name: str | None = None, limit: int = 50) -> list[dict]:
    """Show ref history for a milestone/branch, including rename/delete/prune events."""
    return store.reflog(name=name, limit=limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
