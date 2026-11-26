# The assistants' exam

21 cases for the two AI assistants (12 for the shipper's, 9 for the driver's), asked to the real Gemini model and
graded automatically. Built on logimind-ai's eval: same ideas, same kinds of checks.

| File | What it is |
|---|---|
| `cases.json` | The cases and what a right answer must do |
| `run_eval.py` | Runs them on real Gemini, grades, saves, re-grades and compares runs |
| `selftest.py` | A scripted fake Gemini (no key, no quota): every case must be passable, every replayed mistake caught |
| `run_paperwork_eval.py` | The paperwork agent's checks against the demo documents' answer keys (from logimind-ai) |
| `results/` | `<date_time>/<model>.json` (git-ignored) |

```
python evals/selftest.py                                   # first, always: must end with "Self-test OK"
python evals/run_eval.py --models gemini-3.5-flash-lite    # a full run: about 55 Gemini calls
python evals/run_eval.py --models gemini-3.5-flash-lite --cases driver-best-load,offers-recommend
python evals/run_eval.py --models gemini-3.5-flash-lite --role driver
python evals/run_eval.py --resume evals/results/<run> --models gemini-3.5-flash-lite
python evals/run_eval.py --regrade evals/results/<run>/<model>.json     # new checks on old replies, no calls
python evals/run_eval.py --compare OLD.json NEW.json
```

Every case starts from a fresh database seeded with the simulated demo data (`seed_demo.py`) in a temporary
folder, never `data/kargonaut.db`. The shipper is ნინო ბერიძე (599000001), the driver ლევან გელაშვილი
(599000005). Expected numbers come from that data; if `seed_demo.py` changes, run `selftest.py`: it shows which
cases broke.

## Checks

| Check | Expectation keys |
|---|---|
| right tool | `tools_called`, `tools_called_any`, `tools_not_called`, `forbidden_calls` |
| right arguments | `tool_args` (cities in English or Georgian, truck types as code or label, numbers within 0.5, `{today+1}`) |
| asks instead of guessing | `asks_question`, `forbidden_calls` with `"__nonempty__"` (an invented date or price) |
| right recommendation | `recommends_load` (the first "№N" / "#N" in the reply), `first_named` (which name comes first) |
| right numbers | `reply_numbers` (must appear), `numbers_grounded` (every number from a tool result or the user) |
| content | `reply_contains_all` / `_any`, `reply_not_contains`, `reply_matches`, `reply_not_matches` |
| drafts | `no_draft`, `draft_fields`; always: nothing changed in the data without the user's click |
| language | always: Georgian (at least 60% of letters), no codes like `dry_van`, never "მოგება" (profit) and the other forbidden words |

The grader records the MODEL'S OWN tool arguments, before the Python guards drop an invented date or price: a guess
the guard blocked still fails "asks instead of guessing".

## How to use it

As in logimind-ai: after changing the assistants, run `selftest.py`, then the affected cases, then a full run, then
`--compare` with the previous run. When a case fails, read the actual reply in the results JSON first and decide
whether the agent or the check is wrong. Fix a check only when the reply is genuinely right, then `--regrade`. Never
loosen a check to make a failing agent pass.

## Runs (gemini-3.5-flash-lite)

- 26 Nov, first run (`2026-11-26_2308`): 16/20. Re-graded with two corrected checks: 17/20. The checks: the model
  wrote "ტვირთი #1" (the check only knew "№1"), and wrote "მოგება" (profit) twice, which only "წმინდა მოგება" caught.
  Real mistakes, fixed in the tools: a price invented when the user said "you set the price" (the guard had blocked
  it); an offer drafted at the shipper's price the driver never accepted (now `accept_shipper_price` must be
  explicit); "მოგება" (now forbidden in the driver's prompt). The affected cases then passed 5/5 (`2026-11-26_2317`).
- 26 Nov, full run after the fixes, 21 cases (`driver-offer-shipper-price` added): **21/21**, 49 Gemini calls
  (`2026-11-26_2318`). The current baseline: `--compare` new runs with it.
