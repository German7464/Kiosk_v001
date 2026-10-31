# MVP Baseline Measurement

Related documents: [historical MVP scope](MVP_SCOPE.md), [current ledger](TZ_PROGRESS.md), [approved performance targets](TZ_RECONCILED.md#20-производительность), [documentation index](README.md). Numeric measurements below are unchanged; no benchmark was rerun.

## Verified checkpoint

This is a historical measurement checkpoint. Its results and acceptance limits describe the measured source/environment only. Stage 2 subsequently completed on 2026-10-24 within its agreed scope; use [TZ Progress](TZ_PROGRESS.md#current-stage-3-closure-gates) for the current stage and outstanding checks. Historical pending statements below do not override that ledger.

Measured at 2026-10-18T22:58:27.722593+00:00 (UTC) with `python -m tools.measure_mvp_baseline`. Source artifact: ignored `logs/measurements/mvp-20261018T225827722593Z.json`. This is a local Windows developer checkpoint for TZ sections 20, 21, and stage 2 of section 22, not system acceptance.

Environment: Windows-10-10.0.19045-SP0, AMD64, CPython 3.14.5, pip 26.1.1; processor: Intel64 Family 6 Model 158 Stepping 9, GenuineIntel; physical RAM visible to Windows: 8457334784 bytes (7.88 GiB). Dependency versions match requirements.txt. The machine also hosts other processes; background load, CPU frequency, disk cache, and scheduler timing were not controlled.

## Fixed workload and timing

- Separate four-thread Waitress server process; loopback HTTP clients on the same computer. No browser, persistent display client, or external network is involved.
- Disposable installation populated through authenticated administrative HTTP routes with real CSRF tokens: 100 events (80 active, 20 hidden), 20 tags, and three tags on each event (300 relationships). Long headings and multilingual descriptions are included.
- Ten deterministic synthetic PNGs: five 1920x1080 and five 1080x1920, using grayscale random bytes with seeds 0 through 9, converted to RGB. These are not a representative photographic/video collection.
- Verified API fields and active/hidden filtering, 30 decoded image derivatives, and content version 1 -> 221. Unauthenticated admin redirects with 302; authenticated administration returns 200.
- Three warmups and 50 sequential requests per route; then 1000 requests with ten independent client threads, cycling over the seven routes. Responses are completely read; urllib opens HTTP connections rather than running browser rendering or scripts.
- Durations use perf_counter and include connection/request/full response reading. Median is the ordinary median; p95 is nearest rank, ceil(0.95 * sample count). Throughput divides completed requests by phase wall time; concurrent per-route throughput uses the shared concurrent phase duration.

## Sequential HTTP results

| Route | Samples | Median ms | p95 ms | Maximum ms | Body bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| `/kiosk` | 50 | 15.35 | 16.02 | 16.03 | 2878–2878 |
| `/kiosk/events` | 50 | 15.48 | 16.05 | 16.09 | 3431–3431 |
| `/tv` | 50 | 15.39 | 15.97 | 16.03 | 2064–2064 |
| `/preview` | 50 | 15.46 | 16.15 | 16.41 | 1089–1089 |
| `/api/version` | 50 | 15.50 | 16.25 | 16.78 | 24–24 |
| `/api/events` | 50 | 30.91 | 31.97 | 32.11 | 240656–240656 |
| `/api/tags` | 50 | 15.44 | 16.16 | 16.23 | 2622–2622 |

All 350 measured sequential responses were 200, with zero request errors. HTML timings cover page scaffolds, not visual card rendering; API and image checks are separate.

## Concurrent HTTP results

1000 responses: all 200, zero request errors. Phase duration: 2.476 seconds; throughput: 403.92 requests/second. Median: 16.21 ms; p95: 54.59 ms; maximum: 125.76 ms. Response bodies range from 24 to 240656 bytes; total: 36142630 bytes.

| Route | Samples | p95 ms | Maximum ms |
| --- | ---: | ---: | ---: |
| `/kiosk` | 143 | 20.75 | 80.26 |
| `/kiosk/events` | 143 | 20.99 | 101.13 |
| `/tv` | 143 | 20.96 | 89.87 |
| `/preview` | 143 | 21.38 | 57.38 |
| `/api/version` | 143 | 29.67 | 112.17 |
| `/api/events` | 143 | 60.19 | 125.76 |
| `/api/tags` | 142 | 18.21 | 40.32 |

Waitress reported 986 queue-depth notifications, with an observed maximum reported depth of 7; queue errors: 0. Notifications are aggregated instead of flooding the console. Ten clients sharing four workers produce queueing; this is not a queue-capacity or denial-of-service guarantee.

## Image uploads and sampled server memory

Upload timings cover multipart POST, processing, database write, and redirect/readback. They exclude generating the source PNG and fetching the CSRF token. All uploads succeeded.

| Image | Dimensions | Source bytes | POST/readback ms |
| --- | --- | ---: | ---: |
| 1 | 1920x1080 | 5284169 | 1088.22 |
| 2 | 1920x1080 | 5287838 | 741.79 |
| 3 | 1920x1080 | 5284485 | 739.61 |
| 4 | 1920x1080 | 5286056 | 758.86 |
| 5 | 1920x1080 | 5285060 | 702.88 |
| 6 | 1080x1920 | 5287369 | 636.19 |
| 7 | 1080x1920 | 5288856 | 628.14 |
| 8 | 1080x1920 | 5285638 | 626.34 |
| 9 | 1080x1920 | 5287738 | 636.22 |
| 10 | 1080x1920 | 5284848 | 629.93 |

Initial server working set after readiness: 44978176 bytes (42.89 MiB). Observed maximum: 82980864 bytes (79.14 MiB), across 828 samples at a nominal 100 ms interval during preparation and measurement; zero sampling errors. This is Windows working-set memory (including native/shared pages), not private Python heap, client memory, or a guaranteed peak. Samples can miss short spikes.

Scenario duration including preparation and shutdown: 91.71 seconds. Server shutdown was graceful (exit code 0, no forced termination), and disposable data was removed.

## Reproduction, failures, and limits

Run the command from the repository using the pinned Windows environment. Reports go to ignored logs/measurements; no external URL, existing database, or custom workload is accepted. Requests time out after at most ten seconds; a 180-second watchdog stops an overrun server. Shutdown/cleanup can add time. Failed HTTP checks, invalid data, sampling failures, and incomplete/forced shutdown return nonzero and retain diagnostic report fields. Passwords, cookies, session keys, hostnames, and server addresses are excluded.

No latency acceptance threshold is asserted. In particular, these HTTP timings do not verify the proposed 200 ms UI reaction target, five-second publication activation, Android TV, LAN transfer rates, 100 registered devices, offline display, failover, sustained memory stability, 72-hour operation, or EXE deployment. Automatic refresh, fullscreen, and populated screen layout still need browser/hardware checks. At this measurement checkpoint, stage 2 and overall system acceptance were incomplete. Stage 2 subsequently closed within its recorded boundary; overall system acceptance is still not established. See the current ledger rather than using this historical sentence as current stage status.
