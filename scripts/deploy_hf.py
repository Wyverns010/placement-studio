"""Stage and deploy Placement Studio to a Hugging Face Space (Docker SDK).

    uv run python scripts/deploy_hf.py --dry-run
    uv run python scripts/deploy_hf.py --space <user>/placement-studio

Requires `hf auth login` once for a real upload. The Space's own README.md is generated here;
the repo README is untouched. .env and anything secret-looking is never staged.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INCLUDE_FILES = ["Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock"]
INCLUDE_DIRS = ["app", "config", "prompts", "data", "web"]
SKIP_DIRS = {"node_modules", "dist", "__pycache__", ".pytest_cache", ".venv", ".git", ".cache"}
SKIP_SUFFIXES = {".pyc"}

SPACE_README = """---
title: Placement Studio
emoji: 🎯
colorFrom: purple
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
---

# Placement Studio

Describe a business and get a recommended set of publishers, shopper personas, ad creatives
and a ready-to-launch campaign config. Every input, including the fifteen sample advertisers,
runs live against the model.

Secrets: OPENAI_API_KEY (required), GATE_IMPL (optional)
"""


def _is_secret(rel: str) -> bool:
    name = Path(rel).name.lower()
    if name == ".env.example":
        return False
    return (name == ".env" or name.startswith(".env.") or "secret" in name
            or name.endswith((".pem", ".key")) or name in {"credentials.json", "id_rsa"})


def assert_clean(files: list[str]) -> None:
    bad = [f for f in files if _is_secret(f)]
    assert not bad, f"secret-looking files staged: {bad}"


def _skip(rel: Path) -> bool:
    return (any(part in SKIP_DIRS for part in rel.parts) or rel.suffix in SKIP_SUFFIXES
            or rel.name == ".DS_Store" or _is_secret(rel.as_posix()))


def stage(root: Path, out: Path) -> list[str]:
    """Copy deployable files from `root` into `out`; return sorted relative paths staged."""
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    srcs = [Path(f) for f in INCLUDE_FILES if (root / f).is_file()]
    for d in INCLUDE_DIRS:
        if (root / d).is_dir():
            srcs += [p.relative_to(root) for p in (root / d).rglob("*") if p.is_file()]
    for rel in srcs:
        if _skip(rel):
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dest)
    (out / "README.md").write_text(SPACE_README, encoding="utf-8")
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert_clean(files)
    return files


def _default_space() -> str | None:
    try:
        from huggingface_hub import HfApi
        return f"{HfApi().whoami()['name']}/placement-studio"
    except Exception:  # noqa: BLE001 - not logged in / offline
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--space", help="<user>/placement-studio (default: from your HF login)")
    ap.add_argument("--dry-run", action="store_true", help="stage and print, upload nothing")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="placement-studio-hf-") as tmp:
        files = stage(ROOT, Path(tmp))
        if args.dry_run:
            print(f"Staged {len(files)} files (dry run, nothing uploaded):")
            print("\n".join(f"  {f}" for f in files))
            print("\n--- generated README.md ---\n" + SPACE_README)
            print("OK: no .env or secret-looking files staged.")
            return 0
        space = args.space or _default_space()
        if not space:
            print("No --space given and not logged in. Run `hf auth login` or pass --space.",
                  file=sys.stderr)
            return 2
        from huggingface_hub import HfApi
        api = HfApi()
        api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
        api.upload_folder(folder_path=tmp, repo_id=space, repo_type="space",
                          commit_message="Deploy Placement Studio")
        print(f"Uploaded {len(files)} files -> https://huggingface.co/spaces/{space}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
