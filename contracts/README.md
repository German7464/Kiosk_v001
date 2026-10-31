# Shared client contracts

[Events package v1](events-v1/README.md) documents the existing Python format,
not a replacement protocol. Documentation edition 1 describes the compatibility
tuple `(1, events, events-v1, 1)`; changing this document does not negotiate a new
wire version. Source validation remains authoritative for existing behavior;
resolve discrepancies with PC1 before implementing a divergent client.

Run from the repository root with the existing Python dependencies installed:

```powershell
python -m contracts.events_examples --output logs/contract-examples
```

The destination must not exist. The generator uses synthetic data only, exports
through the real exporter, and checks every case with the independent verifier.
`expected.json` is the cross-platform oracle; `results.json` records the Python
run. Package bytes depend on the checked-out resource files; use one agreed
commit when comparing clients. Generated files belong outside tracked sources.

Requirements/status remain in [the specification](../docs/TZ_RECONCILED.md) and
[the single ledger](../docs/TZ_PROGRESS.md). See [two-PC workflow](../docs/TWO_PC_WORKFLOW.md).
