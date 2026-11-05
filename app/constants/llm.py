import os

MODEL_FAST = os.getenv("OPENAI_MODEL_FAST") or "gpt-5.4-mini"
MODEL_CREATIVE = os.getenv("OPENAI_MODEL_CREATIVE") or "gpt-5.5"
REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT") or "low"
