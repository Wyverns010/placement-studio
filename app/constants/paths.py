from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
EXAMPLES = DATA_DIR / "example_advertisers.txt"
TUNING_PATH = ROOT / "config" / "tuning.yaml"
PROMPTS_DIR = ROOT / "prompts"
WEB_DIST = ROOT / "web" / "dist"
