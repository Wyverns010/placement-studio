"""Placement Studio. Loads .env first, so every module reads the same environment."""
from dotenv import load_dotenv

load_dotenv()  # never overrides variables that are already set
