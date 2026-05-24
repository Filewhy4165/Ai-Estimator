# Benchmark Harness

Use this folder to store repeatable accuracy benchmark inputs and reports.

## Files

- `manifest.example.json` example benchmark manifest
- `results/` recommended output folder for generated benchmark reports

## Quick start

1. Copy `manifest.example.json` to a working file (for example `manifest.local.json`).
2. Replace each `pdf_paths` value with real drawing PDF paths.
3. Add expected labels under each case (`sheet_ids`, `scales_by_sheet`, `analyzed_trades`, `quantity_sanity`).
4. Run:

```powershell
ai-estimator-benchmark `
  --manifest ".\benchmarks\manifest.local.json" `
  --output ".\benchmarks\results\latest.json"
```

The report includes per-case metrics and aggregate averages.
