from __future__ import annotations

from pathlib import Path

import pytest

from scripts import deploy_hf


def test_stage_excludes_secrets_and_has_front_matter(tmp_path):
    root = tmp_path / "repo"
    for p in ["app/x.py", "prompts/p.md", "data/d.json",
              "web/src/main.tsx", "web/node_modules/m/i.js", "web/dist/index.html",
              ".env", "app/.env", "Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock",
              "app/__pycache__/x.pyc"]:
        f = root / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    out = tmp_path / "stage"
    files = deploy_hf.stage(root, out)
    assert ".env" not in files and "app/.env" not in files
    assert "web/src/main.tsx" in files and "app/x.py" in files and "uv.lock" in files
    assert not any("node_modules" in f or f.startswith("web/dist") or "__pycache__" in f
                   for f in files)
    readme = (out / "README.md").read_text()
    assert readme.startswith("---\n")
    for line in ["title: Placement Studio", "sdk: docker", "app_port: 7860", "emoji: 🎯",
                 "colorFrom: purple", "colorTo: pink", "pinned: false"]:
        assert line in readme
    assert "OPENAI_API_KEY" in readme and "README.md" in files


def test_assert_clean_rejects_secret_files(tmp_path):
    with pytest.raises(AssertionError):
        deploy_hf.assert_clean([".env"])
    with pytest.raises(AssertionError):
        deploy_hf.assert_clean(["app/secrets.json"])
    deploy_hf.assert_clean(["app/api.py", ".env.example"])


def test_real_repo_stage_is_clean(tmp_path):
    files = deploy_hf.stage(Path(deploy_hf.ROOT), tmp_path / "s")
    deploy_hf.assert_clean(files)
    assert "data/example_advertisers.txt" in files
