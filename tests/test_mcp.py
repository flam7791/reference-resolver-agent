import json

from mcp import Client

from refresolver.mcp_server import create_server

from .conftest import FakeSource, cand, make_resolver

AUTOR = cand(
    "10.1257/jep.29.3.3",
    "Why Are There Still So Many Jobs? The History and Future of Workplace Automation",
    ["Autor"],
    2015,
)


def server(settings):
    crossref = FakeSource("crossref", {"so many jobs": [AUTOR]})
    return create_server(settings, resolver=make_resolver(settings, crossref=crossref))


async def test_tools_are_listed_as_read_only(settings):
    async with Client(server(settings)) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == {"resolve_citation", "resolve_bibliography"}
    assert all(t.annotations.read_only_hint for t in tools)


async def test_resolve_citation_over_mcp(settings):
    async with Client(server(settings)) as client:
        result = await client.call_tool(
            "resolve_citation", {"citation": "Autor, D. (2015), Why are there still so many jobs?"}
        )
    data = json.loads(result.content[0].text)
    assert data["status"] == "linked" and data["identifier"] == AUTOR.identifier


async def test_resolve_bibliography_over_mcp_respects_the_cap(settings):
    text = "References\n\n" + "\n".join(
        f"Autor, D. (2015), Why are there still so many jobs? copy {i}" for i in range(3)
    )
    async with Client(server(settings)) as client:
        result = await client.call_tool("resolve_bibliography", {"text": text, "max_references": 2})
    data = json.loads(result.content[0].text)
    assert data["skipped"] == 1 and len(data["resolutions"]) == 2


async def test_too_short_citation_is_refused(settings):
    async with Client(server(settings)) as client:
        result = await client.call_tool("resolve_citation", {"citation": "Autor"})
    assert result.is_error


async def test_server_starts_over_stdio_without_an_api_key(tmp_path):
    import sys

    from mcp import StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "refresolver", "serve"],
        env={"REFRESOLVER_CACHE_DIR": str(tmp_path), "ANTHROPIC_API_KEY": ""},
    )
    async with Client(params) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert names == {"resolve_citation", "resolve_bibliography"}
