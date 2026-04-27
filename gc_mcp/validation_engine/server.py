from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.validation_engine.tools import validate_hypotheses
from fastmcp import FastMCP


mcp = FastMCP("validation_engine")


@mcp.tool(name="validate_hypotheses")
def validate_hypotheses_tool(payload: dict) -> dict:
    return validate_hypotheses(payload)


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()
