.PHONY: test dev-api dev-web build-web eval samples samples-offline
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
samples-offline:  # no LLM: verify cached stage 1 still reproduces, rebuild configs, re-stamp
	uv run python scripts/precompute_samples.py --offline
build-web:
	cd web && npm ci && npm run build
