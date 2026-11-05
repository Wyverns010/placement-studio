"""Reading the data pack and the example advertisers."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.constants.catalog import SAMPLE_LABELS
from app.constants.paths import DATA_DIR, EXAMPLES
from app.models.catalog import Catalog


def load_catalog(data_dir: Path = DATA_DIR) -> Catalog:
    """Pattern: factory function. Files in, one validated Catalog out."""
    return Catalog.model_validate({"publishers": json.loads((data_dir / "publishers.json").read_text()),
                                   "personas": json.loads((data_dir / "shopper_personas.json").read_text())})


def load_samples(path: Path = EXAMPLES) -> list[dict]:
    samples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(\d+)\.\s+(.*\S)\s*$", line)
        if match:
            number = int(match.group(1))
            samples.append({"id": number, "label": SAMPLE_LABELS.get(number, f"Example {number}"),
                            "text": match.group(2)})
    return samples
