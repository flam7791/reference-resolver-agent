"""The resolver as MCP tools, so any MCP-capable assistant can call it.

Both tools only read from public registries. They may call the model (which costs money),
so each call is bounded: a maximum number of references and the agent's step budget.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import __version__
from .config import Settings
from .factory import build_resolver
from .report import summary
from .text import bibliography_section, split_entries

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
MAX_CITATION_CHARS = 2000


def create_server(settings: Settings | None = None, resolver=None) -> MCPServer:
    settings = settings or Settings.from_env()
    resolver = resolver or build_resolver(settings)
    server = MCPServer(
        name="reference-resolver",
        title="Reference resolver",
        instructions=(
            "Resolve bibliographic citations to registered works (DOIs). Results have a status: "
            "linked (safe to use), review (a person should confirm the suggestion) or "
            "unresolved. Never present a review suggestion as confirmed."
        ),
        version=__version__,
    )

    @server.tool(annotations=READ_ONLY)
    def resolve_citation(citation: str) -> dict:
        """Resolve one citation, e.g. "Autor, D. (2015), Why are there still so many jobs?,
        Journal of Economic Perspectives". Returns status, identifier, confidence, the reasons,
        and the best alternatives."""
        citation = " ".join(citation.split())
        if not 15 <= len(citation) <= MAX_CITATION_CHARS:
            raise ToolError(f"citation must be 15 to {MAX_CITATION_CHARS} characters long.")
        resolver.reset_meter()
        ref = resolver.parse([citation])[0]
        return resolver.resolve(ref).to_dict()

    @server.tool(annotations=READ_ONLY)
    def resolve_bibliography(text: str, max_references: int = 40) -> dict:
        """Resolve every reference in a document's bibliography (paste the document or just
        its reference list). Returns a summary and one result per reference."""
        if not 1 <= max_references <= 100:
            raise ToolError("max_references must be between 1 and 100.")
        entries = split_entries(bibliography_section(text))
        if not entries:
            raise ToolError("No references found. Paste the reference list, one per line.")
        resolver.reset_meter()
        # Cut before parsing, so the model is never paid to parse references we skip.
        resolutions = resolver.resolve_all(resolver.parse(entries[:max_references]))
        return {
            "summary": summary(resolutions, resolver.meter),
            "skipped": max(0, len(entries) - max_references),
            "resolutions": [r.to_dict() for r in resolutions],
        }

    return server
