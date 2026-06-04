# agykit Dashboard Usage

This is the operator-facing guide for the dashboard’s decision cards.

## What The New Cards Answer

- `Health Center`: is the local runtime healthy enough to keep working?
- `Job Timeline`: what did the current or most recent job do, step by step?
- `Recommended Account/Model`: which account and model should be used next?
- `Quota Forecast`: how fast is quota burning and when does it become risky?
- `Agent Performance Matrix`: which agent is producing the best results for the least cost?

## How To Use It

1. Start the dashboard with `agykit dash`.
2. Use the `Refresh` buttons in the Decision Center for an immediate manual update.
3. Watch the SSE connection indicator. If a source changes, only the affected cards should refresh.
4. Open the `Job Timeline` card when a run fails. It shows the exact sequence of account, model, verify, and rollback events.
5. Check `Health Center` first when the dashboard looks stale or a card is empty.

## Fixture Bundle

The test fixture bundle lives in `tests/fixtures/dashboard/`.

It contains:

- `project/` for project config checks
- `quota-cache.json` for recommendation and forecast checks
- `statusline-latest.json` for statusline checks
- `jobs/` for timeline examples

The fixtures are intentionally small so they can be copied into temp directories during tests.
