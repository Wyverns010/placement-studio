.PHONY: test dev-api dev-web build-web eval samples
test:
	uv run pytest -q
dev-api:
	uv run uvicorn app.api:app --reload
dev-web:
	cd web && npm run dev
eval:
	uv run python -m evals.run
samples:
	uv run python scripts/precompute_samples.py
build-web:
	cd web && npm ci && npm run build
