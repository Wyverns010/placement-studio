"""Code checks on ad copy: invented numbers and claim words, field lengths, generic copy,
parroting the advertiser, and duplicate headlines. Pure functions, no LLM."""
from __future__ import annotations

import re
from typing import NamedTuple

from app.models.ads import Creative
from app.models.tuning import Tuning
from app.prompts import FEEDBACK


class Problem(NamedTuple):
    """One thing code rejected in an ad; `kind` drives retry behaviour, `message` is the text."""
    kind: str  # fact_number | fact_claim | length | generic_copy | parroting | headline_duplicate |
    # headline_product | headline_unchanged | missing
    message: str


_NUMBER = re.compile(r"\$?\d[\d,.]*%?")


def _numbers(text: str) -> set[str]:
    """Digit cores of every number token: $, %, commas and trailing punctuation stripped."""
    return {m.strip("$%").replace(",", "").rstrip(".,") for m in _NUMBER.findall(text)}


def _has_word(word: str, text: str) -> bool:
    return re.search(r"(?<![\w#])" + re.escape(word) + r"(?![\w])", text, re.IGNORECASE) is not None


def check_facts(creative: Creative, input_text: str, t: Tuning) -> list[str]:
    """Violation messages: numbers/claim words absent from the input, and over-length fields."""
    return [p.message for p in fact_problems(creative, input_text, t)]


def fact_problems(creative: Creative, input_text: str, t: Tuning) -> list[Problem]:
    violations: list[Problem] = []
    copy = f"{creative.headline} {creative.body} {creative.cta}"
    known = _numbers(input_text)
    for n in sorted(_numbers(copy)):
        if n not in known:
            violations.append(Problem("fact_number", FEEDBACK["fact_number"].format(number=n)))
    for w in t.creative.claim_words:
        if _has_word(w, copy) and not _has_word(w, input_text):
            violations.append(Problem("fact_claim", FEEDBACK["fact_claim"].format(word=w)))
    for field, limit in (
        ("headline", t.creative.headline_max_chars),
        ("body", t.creative.body_max_chars),
        ("cta", t.creative.cta_max_chars),
    ):
        n = len(getattr(creative, field))
        if n > limit:
            violations.append(Problem("length", FEEDBACK["length"].format(field=field, n=n, limit=limit)))
    return violations


_DASH = r"(?:-|–|—|to)"
# Explicit age context: "ages 25+", "ages 25-34", "ages 25 and up", "aged 30 and over".
_AGE_CONTEXT = re.compile(
    r"\b(?:ages?\s+\d{1,2}|aged\s+\d{2})\s*(?:\+|and\s+(?:up|over|older)\b|" + _DASH + r"\s*\d{1,2}\b)",
    re.IGNORECASE)
# A bare two-number range ("18-24"); only an age when both ends are plausible ages and no unit
# follows ("24-48 hours", "20-30 oz", "20-30%"). "25-34 year olds" is still an age.
_UNITS = (r"(?:%|(?:percent|hours?|hrs?|days?|nights?|minutes?|mins?|seconds?|secs?|weeks?|months?"
          r"|years?(?![\s-]*olds?)|yrs?|oz|ml|l|liters?|litres?|lbs?|pounds?|kg|g|grams?|cm|mm|in"
          r"|inch(?:es)?|ft|feet|servings?|packs?|pieces?|pcs|count|ct|calories|cal|mg)\b)")
_BARE_RANGE = re.compile(r"\b(\d{2})\s*" + _DASH + r"\s*(\d{2})\b(?!\s*" + _UNITS + ")", re.IGNORECASE)
_UNDER = re.compile(r"\bunder\s+\$\s?\d[\d,]*", re.IGNORECASE)


def _plain(text: str) -> str:
    """Lowercase, dashes unified ("25 to 34" -> "25-34") and whitespace collapsed, for 'did the
    advertiser write it'."""
    text = re.sub(r"(\d)\s*(?:–|—|-|\bto\b)\s*(\d)", r"\1-\2", text.lower())
    text = re.sub(r"\s*[–—-]\s*", "-", text)
    return " ".join(text.split())


def _in_source(phrase: str, source: str) -> bool:
    """Whole-word containment ('for men' is not inside 'for mental')."""
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", source) is not None


def _phrase_pattern(phrase: str) -> re.Pattern:
    """A banned phrase with space/hyphen variants and simple inflections of its last word
    ("elevate" -> elevates/elevated/elevating; "high-quality" -> "high quality")."""
    words = re.split(r"[\s-]+", phrase.strip().lower())
    *head, last = words
    if last.endswith("e"):
        tail = re.escape(last[:-1]) + r"(?:e|es|ed|ing)"
    elif last.isalpha():
        tail = re.escape(last) + r"(?:s|es|ed|ing)?"
    else:
        tail = re.escape(last)
    body = r"[\s-]+".join([re.escape(w) for w in head] + [tail])
    return re.compile(r"(?<![\w#])" + body + r"(?!\w)", re.IGNORECASE)


def _is_age_range(m: re.Match, t: Tuning) -> bool:
    lo, hi = t.creative.age_range_bounds
    return all(lo <= int(g) <= hi for g in m.groups())


def generic_problems(creative: Creative, input_text: str, t: Tuning) -> list[Problem]:
    """Headline/body copy that restates targeting (age ranges, "for women"), uses a price band
    ("under $50") or a banned filler phrase. Anything the advertiser wrote themselves is allowed."""
    copy = f"{creative.headline} {creative.body}"
    source = _plain(input_text)
    audience = re.compile(r"\bfor\s+(?:" + "|".join(re.escape(w) for w in t.creative.audience_words)
                          + r")(?![\w'’])", re.IGNORECASE)
    out: list[Problem] = []
    found: list[tuple[str, str]] = []  # (feedback key, phrase as written)
    found += [("generic_age", m.group(0)) for m in _AGE_CONTEXT.finditer(copy)]
    found += [("generic_age", m.group(0)) for m in _BARE_RANGE.finditer(copy)
              if _is_age_range(m, t) and not any(m.start() >= a.start() and m.end() <= a.end()
                                                 for a in _AGE_CONTEXT.finditer(copy))]
    found += [("generic_audience", m.group(0)) for m in audience.finditer(copy)]
    found += [("generic_price_band", m.group(0)) for m in _UNDER.finditer(copy)]
    for key, phrase in found:
        p = _plain(phrase)
        if not _in_source(p, source):
            out.append(Problem("generic_copy", FEEDBACK[key].format(phrase=p)))
    for w in t.creative.banned_phrases:
        pat = _phrase_pattern(w)
        if pat.search(copy) and not pat.search(input_text):
            out.append(Problem("generic_copy", FEEDBACK["generic_phrase"].format(phrase=w)))
    return out


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _contains(seq: list[str], run: list[str]) -> bool:
    n = len(run)
    return any(seq[i:i + n] == run for i in range(len(seq) - n + 1))


def parroting_problems(creative: Creative, input_text: str, persona_name: str,
                       t: Tuning) -> list[Problem]:
    """At most one problem when the headline or body copies the advertiser: a run of
    creative.parrot_ngram words, or a whole sentence of at least parrot_sentence_min_words words
    (punctuation- and case-insensitive). Reusing single facts or short phrases is fine."""
    n, min_words = t.creative.parrot_ngram, t.creative.parrot_sentence_min_words
    src = _tokens(input_text)
    grams = {tuple(src[i:i + n]) for i in range(len(src) - n + 1)}
    sentences = [w for w in (_tokens(x) for x in re.split(r"(?<=[.!?])\s+|\n+", input_text))
                 if len(w) >= min_words]
    for field in (creative.headline, creative.body):
        words = _tokens(field)
        hit = next((list(g) for i in range(len(words) - n + 1)
                    if (g := tuple(words[i:i + n])) in grams), None)
        hit = hit or next((sw for sw in sentences if _contains(words, sw)), None)
        if hit:
            return [Problem("parroting", FEEDBACK["parroting"].format(persona=persona_name,
                                                  phrase=" ".join(hit)))]
    return []


def ad_problems(creative: Creative, input_text: str, persona_name: str, t: Tuning) -> list[Problem]:
    """Everything code checks on one ad: facts, lengths, generic copy and parroting."""
    return (fact_problems(creative, input_text, t) + generic_problems(creative, input_text, t)
            + parroting_problems(creative, input_text, persona_name, t))


def normalise_headline(text: str) -> str:
    """Lowercase with punctuation and whitespace removed, for duplicate checks."""
    return re.sub(r"[\W_]+", "", text.lower())


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def headline_similarity(a: str, b: str) -> float:
    """Token-set Jaccard of two headlines' lowercase words (1.0 = same words)."""
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 1.0


def headlines_similar(a: str, b: str, threshold: float) -> bool:
    return normalise_headline(a) == normalise_headline(b) or headline_similarity(a, b) >= threshold


def headline_problems(creatives: list[Creative], product: str | None,
                      names: dict[str, str], threshold: float = 1.0) -> dict[str, list[Problem]]:
    """Per persona_id: a headline that repeats an earlier persona's (in order) or is just the
    product name. `names` maps persona_id -> display name."""
    out: dict[str, list[Problem]] = {}
    seen: list[tuple[str, str]] = []  # (headline, persona_id)
    prod = normalise_headline(product or "")
    for c in creatives:
        h = normalise_headline(c.headline)
        if prod and h == prod:
            out.setdefault(c.persona_id, []).append(Problem("headline_product", FEEDBACK["headline_product"]))
        else:
            dup = next((pid for hl, pid in seen if headlines_similar(hl, c.headline, threshold)), None)
            if dup:
                out.setdefault(c.persona_id, []).append(
                    Problem("headline_duplicate", FEEDBACK["headline_duplicate"].format(name=names.get(dup, dup))))
            else:
                seen.append((c.headline, c.persona_id))
    return out
