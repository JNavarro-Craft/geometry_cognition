from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.domain_interpreter.tools import generate_domain_interpretations
from fastmcp import FastMCP


mcp = FastMCP("domain_interpreter")


@mcp.tool(name="generate_domain_interpretations")
def generate_domain_interpretations_tool(payload: dict, profile: str = "prefab") -> dict:
    return generate_domain_interpretations(payload, profile=profile)


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()
