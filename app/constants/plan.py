import re

GEO = ["US"]  # every catalog publisher is US-based
PACE_WORDS = {"front_loaded": "Front-loaded", "even": "Even", "accelerated": "Accelerated"}
AMOUNT = re.compile(r"(\d+(?:[.,]\d+)*)\s*(k|m|thousand|million|mil)?\b", re.IGNORECASE)  # "$5k", "12,500"
AMOUNT_UNITS = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mil": 1e6, "million": 1e6}

NOTE_NOT_READ = "Couldn't apply your note, so this is the standard config."
NOTE_BUDGET = "Budget set to ${usd:,.0f}/mo from your note."
NOTE_BUDGET_REFUSED = "Kept the budget: ${usd:,.0f} isn't written in your note or is outside ${low:,.0f}–${high:,.0f}."
NOTE_DROPPED = "Dropped {name} from the line items because of your note."
NOTE_NOT_NAMED = "Kept {name}: your note doesn't name it."
NOTE_KEEP_ONE = "Kept every publisher: a note can't remove every publisher."
NOTE_PACING = "Pacing set to {word} because of your note."
