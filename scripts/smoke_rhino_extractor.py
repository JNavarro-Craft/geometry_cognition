from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.rhino_extractor.tools import extract_objects


def main() -> None:
    payload = {"input_path": "tests/fixtures/normalized_objects.sample.json"}
    result = extract_objects(payload)
    print(
        {
            "status": result.get("status"),
            "object_count": len(result.get("objects", [])),
            "message": result.get("message"),
        }
    )


if __name__ == "__main__":
    main()
