from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import validate


CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "contracts"


def parse_contract_version(contract_name: str) -> str:
    if ".v" not in contract_name:
        raise ValueError(f"Contract name has no version suffix: {contract_name}")
    return contract_name.rsplit(".v", 1)[-1].split(".json", 1)[0]


def load_schema(contract_filename: str) -> dict[str, Any]:
    schema_path = CONTRACTS_DIR / contract_filename
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_payload(contract_filename: str, payload: dict[str, Any]) -> None:
    schema = load_schema(contract_filename)
    validate(instance=payload, schema=schema)
