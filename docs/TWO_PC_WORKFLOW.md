# Workstation and laboratory workflow

## Ownership and working copy

Follow [AGENTS.md](../AGENTS.md) for roles, Flash handoff and GitHub publication. Use the notebook checkout on work/windows-layout-checks for server, Windows and Android work. PC1 is a fallback and historical evidence source. PC2 hosts the lab VMs and retains the former Android checkout as a recovery copy. Use the current notebook development environment and its local Android configuration.

Resolve the checkout, environment, lab endpoints, SSH identities and Android serial from the notebook's private configuration and the assigned test inventory. Confirm the actual target and retain strict host-key checks. Use the [lab boundaries](TEST_LAB_POLICY.md) and [GUI harness](WINDOWS_GUI_HARNESS.md). Report an access blocker with the failed operation and continue checks that do not depend on it.

## Recovery and evidence

See [source recovery](DEVELOPMENT_RECOVERY.md) for the GitHub checkpoint and recovery limits, and the [ledger](TZ_PROGRESS.md) for stage scope and acceptance. The November migration retained the previous checkouts and historical test environments. Reuse matching existing evidence. Network availability and artifacts on a recovery machine need their own checks when relevant.
