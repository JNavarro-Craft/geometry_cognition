from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.evidence_graph.tools import build_evidence_graph
from fastmcp import FastMCP


mcp = FastMCP("evidence_graph")


@mcp.tool(name="build_evidence_graph")
def build_evidence_graph_tool(payload: dict) -> dict:
    return build_evidence_graph(payload)


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()
