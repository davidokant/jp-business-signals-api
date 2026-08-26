from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from .schemas import Company, Signal


@dataclass(frozen=True, slots=True)
class Dataset:
    companies: list[Company]
    signals: list[Signal]


def load_dataset(path: Path) -> Dataset:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    companies = TypeAdapter(list[Company]).validate_python(raw.get("companies", []))
    signals = TypeAdapter(list[Signal]).validate_python(raw.get("signals", []))
    company_numbers = {company.corporate_number for company in companies}
    missing = sorted({signal.corporate_number for signal in signals} - company_numbers)
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Signals reference companies missing from this dataset: {missing_text}")
    return Dataset(companies=companies, signals=signals)


def sample_dataset_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "sample_dataset.json"
