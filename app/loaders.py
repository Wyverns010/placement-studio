"""Reading the data pack, the example advertisers and the tuning file."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from app.constants.catalog import SAMPLE_LABELS
from app.constants.paths import DATA_DIR, EXAMPLES, TUNING_PATH
from app.models.catalog import Catalog, Persona, Publisher
from app.models.tuning import Tuning


def load_catalog(data_dir: Path = DATA_DIR) -> Catalog:
    publishers = json.loads((data_dir / "publishers.json").read_text())
    personas = json.loads((data_dir / "shopper_personas.json").read_text())
    return Catalog.build([Publisher.from_raw(raw) for raw in publishers],
                         [Persona.from_raw(raw) for raw in personas])


def load_samples(path: Path = EXAMPLES) -> list[dict]:
    samples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(\d+)\.\s+(.*\S)\s*$", line)
        if match:
            number = int(match.group(1))
            samples.append({"id": number, "label": SAMPLE_LABELS.get(number, f"Example {number}"),
                            "text": match.group(2)})
    return samples


def load_tuning(path: Path = TUNING_PATH) -> Tuning:
    return Tuning(**yaml.safe_load(path.read_text()))
