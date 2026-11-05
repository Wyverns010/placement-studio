from app.models.brief import ClarifyQuestion

ANSWERS_HEADER = "\n\nAdditional details:\n"  # clarify answers are appended to the text after this

# the gate's business signal from the brief's audience_type; "unclear" stays below the
# business threshold so a vague buyer falls through to the clarity check (clarify)
BUSINESS_PROB = {"business": 1.0, "not_shoppable": 1.0, "unclear": 0.25, "consumer": 0.0}

NO_SIGNAL_QUESTIONS = [
    ClarifyQuestion(question="What do you sell?",
                    options=["Physical product", "Subscription", "App or service", "Food or drink"]),
    ClarifyQuestion(question="Who usually buys it?", options=["Women", "Men", "Parents", "Everyone"]),
    ClarifyQuestion(question="Roughly what does it cost?", options=["Under $30", "$30–100", "$100+"]),
]

# what a clarify question is about, by its words: the same topic is never asked twice
CLARIFY_TOPICS = {"audience": ("who ", "whom", "audience", "age", "customer"),
                  "price": ("price", "cost", "spend", "how much", "$"),
                  "product": ("what kind", "what type", "product", "category", "what do you sell", "service")}

NOTE_NOT_READ = "Couldn't apply your note, so this is the standard result."
# a note's word counts as a name's word at this similarity (difflib ratio): "optimiser" ~ "optimizer" (0.89)
NAME_MATCH = 0.8
NOTE_DROPPED = "Left out {name} because of your note."
NOTE_NOT_NAMED = "Kept {name}: your note doesn't name it."
NOTE_ADDED = "Added {words} to the brief's categories because of your note."
NOTE_REMOVED = "Removed {words} from the brief's categories because of your note."
NOTE_AGES = "Set the audience ages to {low}–{high} because of your note."
NOTE_AGES_REFUSED = "Kept the brief's ages: {low}–{high} is outside {floor}–{ceiling}."
NOTE_KEEP_ONE = "Kept every publisher: a note can't remove every publisher."
NOTE_GATE = "The gate decided {outcome}; a note can't change that."
