# Kiosk test laboratory

## Boundaries

- For an approved assignment use the named test VMs, test installations, fixture data and assigned test-device package. Routine lab deployments, restarts, guest/test settings, time corrections, checks and task-owned cleanup are covered without repeated owner approval. Use required lab-only passwords, keys and certificates through local tools. Keep their values out of model input, console output, evidence and Git. Keep required sandbox and environment confirmations.
- Keep production, live data, original phone apps, unrelated services and host/network settings outside the assignment. Preserve unrelated trust, registrations, retained baselines and rollback copies. Isolate destructive test fixtures. Keep TLS validation and strict SSH host keys. Use the [VM GUI harness](WINDOWS_GUI_HARNESS.md) and the exact ADB serial. Check time against a verified UTC reference and applicable validity windows before time-sensitive work and after a reboot, resume or restore.
- Reuse healthy authorized fixtures, and record identities, retained state, evidence and cleanup in the [ledger](TZ_PROGRESS.md). Restore temporary fault conditions and stop unused task resources. Existing historical identities and scope are in the ledger and Git history. Schedule lab-secret rotation and removal of test VMs for release preparation.
