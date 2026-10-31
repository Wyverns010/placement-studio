# Shopper graph vs the formula (2026-10-31)

**The rule** (set before measuring): ship graph matching only if its stage-1 outcome accuracy is
≥ the formula's on **both** splits, **and** its must-hit rate is ≥ the formula's, **and** it avoids
100% of must-not publishers. Otherwise keep the formula. Behind that sits the point of the
experiment: switch to graph matching only **if it measurably helps**.

## Verdict: keep the formula

The graph **ties** the formula on every labelled number. Train: 85/85 vs 85/85, must-hit 96% vs 96%,
must-not 100%. Held out: 35/36 vs 35/36, must-hit 100% vs 100%, must-not 100%. A tie meets the
rule's minimum, but it is not a measured improvement, so `match.impl` stays `formula`. The tie
is also fragile. Of the 120 graph settings that tie on train, only 58 still tie on the held-out
split; the rest recommend a must-not publisher there. All the code stays behind the switch
(`match.impl: graph` in `config/tuning.yaml`).

Why a tie is the expected result here: Disco's Shopper Graph is built from cross-brand
**purchase** edges. The data pack has none: no co-purchase data, no shopper-level records. Ours is
built only from what the formula already reads: the category taxonomy, persona affinities and
audience demographics. Re-wiring the same facts as a graph can't learn anything they don't
contain. With real co-purchase edges (shopper → brand bought) the same walk and paths code
would apply unchanged, and this comparison is the harness to re-run.

## Update 2026-11-01: personas

The first comparison only scored publishers. 79 cases now also carry persona labels, written
before measuring (`must_personas`: shoppers who obviously belong; `must_not_personas`: ones who
obviously don't, e.g. the Pet Parent for golf clubs). The labels are hand-written and the
measurements are offline from the same `.cache/llm` briefs ($0).

The formula had two bugs: a persona only matched its exact term, so `supplements` missed a brief
read as `wellness_dtc` (its parent) and `home_goods` missed `home`; and the stretch fill picked
any persona with a good price and age fit, so the Pet Parent was added to candles and golf clubs.
The fix, all in `app/match.py` and `config/tuning.yaml`:
- **Family affinity** (0.7): the persona term is a parent or child of a brief term (catalog
  groups + `affinity_parents`). **Sibling** (0.35): both terms sit under the same parent category.
- **Shopping modes**: the Gifter matches a `gifting` brief and the Sustainability Buyer a
  `sustainable` one (`persona.attribute_affinities`), as their descriptions say.
- **Niche penalty** (0.2): a persona whose affinities sit in one category (the Pet Parent) loses
  0.2 when the brief has no affinity to it at all.
- **Stretch fill** takes personas with some affinity first.

| | persona must-hit train | must-not avoided train | must-hit held-out | must-not avoided held-out |
|---|---|---|---|---|
| formula, before | 87% | 84% | 86% | 74% |
| graph, before | 94% | 91% | 93% | 83% |
| **formula, after (live)** | **92%** | **98%** | **86%** | **100%** |
| graph, after | 94% | 96% | 93% | 96% |

Values were chosen on train. Family 0.6, 0.7 and 0.8 tie, sibling 0.35 and 0.5 tie (0.35 kept,
set before the sweep), and a niche penalty of 0.1 to 0.3 ties. Publisher numbers are unchanged
(85/85, 35/36, must-hit 96%/100%, must-not 100%).

**Verdict: the formula stays.** The graph finds more of the shoppers who belong (93% vs 86%
held out), but it lets more wrong ones in (96% vs 100%). Neither wins on both numbers. The
remaining formula misses come from how the brief was read: protein bars and "running shoes"
were read as `groceries` and `shoes`, which carry no Fitness Enthusiast term, so no matcher
reaches it.

## What was built

- `app/graph.py` builds a typed, weighted, undirected graph from the data pack. Nodes are 80
  category terms, 20 publishers and 10 personas. It has 5 kinds of edges; their weights are in
  `config/tuning.yaml` under `graph:`.
  - Publisher to its category: 1.0.
  - Publisher to a subcategory: 0.85, or 0.2 for an attribute tag.
  - Subcategory or interest term to its parent category (catalog groups plus `affinity_parents`): 0.7.
  - Persona to each affinity: 1.0.
  - Persona to publisher: 0.4 × audience fit, only when the fit is ≥ 0.6. The audience fit is
    the persona read as a brief and scored by the existing `_audience` and `_income` factors,
    so it adds no new magic numbers.
- Scoring walks every simple path of ≤ 3 edges from the brief's categories (seed 1.0) and
  adjacent categories (seed 0.5). A path's weight is the seed × the edge weights × a
  pass-through discount for each inner node (term 0.5, persona 0.2, publisher 0.3), like a
  PageRank damping step. A node's graph score is
  `1 − (1−w₁)·Π(1 − 0.25·wₖ)` over its 3 strongest paths. The strongest path counts in full;
  the others count only as corroboration.
- The graph score replaces only the **category** factor (publishers) or the **affinity**
  factor (personas). Audience, income, the AOV factor, the AOV gate (so luxury and price
  logic still apply), the conflict penalty, the cutoffs and the 4-factor `Factor` list are
  all unchanged. Each publisher and persona also gets a `path` field: its top 2 paths in
  plain words.
  - `pet food → Pawline`; `pet food → pet → Tailcrate`
  - `home → home goods → The Gifter` (candles); `refillable products → The Sustainability Buyer`
  - `pet → Ruffco → The Value-Conscious Shopper` (a co-shopper hop via the publisher's audience)

## How it was measured ($0, offline)

`uv run python -m evals.compare_graph` runs the real stage-1 pipeline (understand → gate → match)
on all 121 cases, once per `match.impl`, on the **same** understood brief. Understand answers come
from the disk cache `.cache/llm` (121/121 hits). A cache miss fails the case instead of calling a
model, so there were no live calls and no spend. Clarify questions are stubbed; they never change
the outcome or the publishers.

**Tuning was chosen on train only** (`--sweep`, 288 settings). A setting qualifies when it ties
the formula on train accuracy and must-hit and has no must-not. Among those, the one closest to
the formula's recommended sets wins. The held-out split was not used to choose. It was seen,
though: the first, untuned graph run covered all 121 cases, and `--sweep` reports held-out for
every setting.

- No setting beats the formula's train must-hit (50/52).
- The 2 misses are both the refillable-cleaning brief (given-09 and its paraphrase): it must
  hit Pantrygood, and neither matcher reaches it.
- Without the term pass-through discount (`through.term` 1.0), the walk bridges categories
  through shared subcategory words. For example, `wellness dtc → women → apparel → Heartfoot`
  put 4 apparel publishers on the value-supplements brief. Only 18 of 72 such settings keep
  must-not at 100% on held-out.

## Results

| split | n | outcome acc. formula | outcome acc. graph | must-hit formula | must-hit graph | must-not formula | must-not graph | rec. set overlap | persona overlap |
|---|---|---|---|---|---|---|---|---|---|
| train | 85 | 85/85 (100.0%) | 85/85 (100.0%) | 96% | 96% | 100% | 100% | 95% | 71% |
| test | 36 | 35/36 (97.2%) | 35/36 (97.2%) | 100% | 100% | 100% | 100% | 94% | 72% |
| all | 121 | 120/121 (99.2%) | 120/121 (99.2%) | 97% | 97% | 100% | 100% | 95% | 72% |

errors: none

### The brief's 15 examples

| case | expected | formula | graph | formula picks | graph picks | personas (formula / graph) |
|---|---|---|---|---|---|---|
| given-01 | proceed | ✓ proceed | ✓ proceed | Pawline, Ruffco, Tailcrate | Pawline, Ruffco, Tailcrate | same |
| given-02 | proceed | ✓ proceed | ✓ proceed | Linden Park, Marlowe & Co., Stride & Stem, Daily Form, Movewell | Linden Park, Marlowe & Co., Movewell, Stride & Stem, Daily Form | Fitness Enthusiast, Sustainability Buyer, Gen Z Aesthete / Fitness Enthusiast, Sustainability Buyer, Gifter, Gen Z Aesthete, Value-Conscious Shopper |
| given-03 | proceed | ✓ proceed | ✓ proceed | Pop & Sip | Pop & Sip | same |
| given-04 | proceed | ✓ proceed | ✓ proceed | Northbed, Hearthstone Goods | Northbed, Hearthstone Goods | Gen Z Aesthete, Pet Parent, Fitness Enthusiast / Gen Z Aesthete, Gifter, Affluent Classic, Sustainability Buyer |
| given-05 | clarify | ✓ clarify | ✓ clarify | – | – | same |
| given-06 | weak_fit | ✓ weak_fit | ✓ weak_fit | Movewell, Marlowe & Co., Linden Park | Movewell, Marlowe & Co., Linden Park | Fitness Enthusiast, Gifter, Value-Conscious Shopper, Wellness Optimizer, Affluent Classic / Fitness Enthusiast, Gifter, Value-Conscious Shopper, Affluent Classic, Wellness Optimizer |
| given-07 | out_of_scope | ✓ out_of_scope | ✓ out_of_scope | – | – | same |
| given-08 | clarify | ✓ clarify | ✓ clarify | – | – | same |
| given-09 | proceed/weak_fit | ✓ proceed | ✓ proceed | Northbed, Hearthstone Goods | Northbed, Hearthstone Goods | Sustainability Buyer, Wellness Optimizer, Busy Parent / Sustainability Buyer, Gifter, Affluent Classic, Gen Z Aesthete |
| given-10 | weak_fit | ✓ weak_fit | ✓ weak_fit | Marlowe & Co., Linden Park, Stride & Stem | Marlowe & Co., Linden Park, Stride & Stem | Gen Z Aesthete, Wellness Optimizer, Affluent Classic / Gen Z Aesthete, Gifter, Affluent Classic |
| given-11 | proceed | ✓ proceed | ✓ proceed | Pantrygood, Swiftcart, Kitchenly | Pantrygood, Swiftcart, Kitchenly | Value-Conscious Shopper, Wellness Optimizer, Busy Parent / Value-Conscious Shopper, Wellness Optimizer, Convenience-First Millennial, Busy Parent, Gifter |
| given-12 | proceed | ✓ proceed | ✓ proceed | Pawline, Ruffco, Tailcrate | Pawline, Ruffco, Tailcrate | Pet Parent, Wellness Optimizer, Busy Parent / Pet Parent, Busy Parent, Value-Conscious Shopper |
| given-13 | proceed | ✓ proceed | ✓ proceed | Daily Form | Daily Form | Wellness Optimizer, Value-Conscious Shopper, Gen Z Aesthete / Wellness Optimizer, Value-Conscious Shopper, Fitness Enthusiast |
| given-14 | proceed | ✓ proceed | ✓ proceed | Northbed, Hearthstone Goods | Northbed, Hearthstone Goods | same |
| given-15 | no_signal | ✓ no_signal | ✓ no_signal | – | – | same |

Rec. set overlap is the mean Jaccard of the recommended publishers on cases both matchers built.
The persona overlap is lower (72%), and **personas are where the graph differs most**. The graph
connects `home` to the `home goods` affinity through `affinity_parents`, a link the formula uses
only for publishers. So for the candles brief (given-04), the graph picks The Gifter, The Affluent
Classic and The Sustainability Buyer instead of the formula's stretch fill (The Pet Parent, The
Fitness Enthusiast). That looks better, but there are no persona labels, so it is unmeasured.
That makes it the cheapest follow-up: give the formula's persona affinity the same
`affinity_parents` link and label a persona set.

### Outcome changes (0)

- none

### Publishers graph recommends that formula does not (6)

- clear-apparel-1 (test): graph adds **Stride & Stem** (fit 0.706 vs 0.695 in formula). Graph paths: women → Stride & Stem; plus size → apparel → Stride & Stem
- clear-instant_delivery-3 (train): graph adds **Pantrygood** (fit 0.414 vs 0.12 in formula). Graph paths: instant delivery → groceries → Pantrygood; instant delivery → Swiftcart → groceries → Pantrygood
- clear-meal_kits-1 (train): graph adds **Pantrygood** (fit 0.479 vs 0.158 in formula). Graph paths: meal kits → groceries → Pantrygood; meal kits → Kitchenly → groceries → Pantrygood
- clear-meal_kits-2 (test): graph adds **Pantrygood** (fit 0.479 vs 0.158 in formula). Graph paths: meal kits → groceries → Pantrygood; meal kits → Kitchenly → groceries → Pantrygood
- clear-wellness_dtc-1 (train): graph adds **Linden Park** (fit 0.6 vs 0.592 in formula). Graph paths: women → Linden Park; women → apparel → Linden Park
- weak-dining (train): graph adds **Marlowe & Co.** (fit 0.058 vs 0.054 in formula). Graph paths: home goods → The Gifter → apparel → Marlowe & Co.

### Publishers formula recommends that graph does not (12)

- clear-apparel-1 (test): formula adds **Cloudfoot** (fit 0.712 vs 0.607 in graph). Graph paths: plus size → apparel → Cloudfoot; women → apparel → Cloudfoot
- clear-apparel-2 (test): formula adds **Everbody** (fit 0.474 vs 0.387 in graph). Graph paths: basics → apparel → Everbody; socks → apparel → Everbody
- clear-apparel-2 (test): formula adds **Cloudfoot** (fit 0.431 vs 0.35 in graph). Graph paths: basics → apparel → Cloudfoot; socks → apparel → Cloudfoot
- clear-home-1 (train): formula adds **Stride & Stem** (fit 0.559 vs 0.218 in graph). Graph paths: premium basics → apparel → Stride & Stem; premium basics → apparel → shoes → Stride & Stem
- clear-home-1 (train): formula adds **Linden Park** (fit 0.519 vs 0.201 in graph). Graph paths: premium basics → apparel → Linden Park; premium basics → apparel → classic → Linden Park
- clear-home-1 (train): formula adds **Cloudfoot** (fit 0.488 vs 0.188 in graph). Graph paths: premium basics → apparel → Cloudfoot; premium basics → apparel → activewear → Cloudfoot
- clear-home-2 (train): formula adds **Stride & Stem** (fit 0.634 vs 0.25 in graph). Graph paths: premium basics → apparel → Stride & Stem; premium basics → apparel → shoes → Stride & Stem
- clear-home-2 (train): formula adds **Linden Park** (fit 0.591 vs 0.232 in graph). Graph paths: premium basics → apparel → Linden Park; premium basics → apparel → classic → Linden Park
- clear-home-2 (train): formula adds **Cloudfoot** (fit 0.558 vs 0.218 in graph). Graph paths: premium basics → apparel → Cloudfoot; premium basics → apparel → activewear → Cloudfoot
- clear-wellness_dtc-1 (train): formula adds **Heartfoot** (fit 0.674 vs 0.544 in graph). Graph paths: women → apparel → Heartfoot; women → Movewell → apparel → Heartfoot
- weak-dining (train): formula adds **Studiogrid** (fit 0.054 vs 0.054 in graph). Graph paths: –
- adv-multi (test): formula adds **Northbed** (fit 0.555 vs 0.21 in graph). Graph paths: home goods → home → Northbed; pet supplies → The Pet Parent → Northbed

## Reproduce

    uv run python -m evals.compare_graph            # tables above (all 121 cases, $0)
    uv run python -m evals.compare_graph --sweep    # the train-only tuning sweep
    uv run pytest -q tests/test_graph.py
