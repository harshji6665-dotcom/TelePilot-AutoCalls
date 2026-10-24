# TelePilot 1.5.0 — 200-account Docker VPS release

Prepared **22 October 2026** for the requested **8-vCPU / 64-GB Linux VPS**. This release supports a bounded **200-saved-account pool** and corresponding finite/unlimited account allowances. It is not a measured 200-live-account/RTC capacity result, a user-VPS deployment or a permanent-uptime/no-revocation guarantee. Telegram-invalidated keys cannot be restored by this code, RAM, backups or restart.

## Final evidence

| Check | Result |
|---|---|
| Full source regression suite | **706 passed in 149.80 seconds** |
| Built-image regressions | **All 706 unique cases passed**, across 8 isolated disposable-Mongo batches |
| Image batch composition/time | Seven batches of 90 + one of 76; **112.35 seconds** summed batch execution wall time, excluding image build/database/container preparation |
| Retained / added coverage | All **641** prior cases retained + **65** capacity/VPS/watchdog cases |
| Lint / formatting | Passed; **70 Python files** under app/scripts/tests |
| Source / image dependency checks | `pip check` passed; pinned SDK/API/native signature checks passed |
| Python compilation / shell / browser JS | Passed |
| JSON/YAML / Compose | Both VPS variants and both optional HTTPS combinations validated; stale 100-account env is overridden to 200 by the VPS profile |
| Tested image tag | `telepilot:1.5.0` |
| Tested image ID | `sha256:818e94bf219f76dc5a16b11c9734fee84b0e33dc47d9f6b8c77950af7497e44a` |
| Exact runtime/source inventory | **47 matching file hashes**, including **35 Python app modules**, templates, scripts, original asset, public config and pinned requirements |
| Tested source byte identity | All **70 Python file hashes** match the source-suite snapshot |
| Restricted actual runtime | UID **10001**, read-only image root, tmpfs, no Linux capabilities, `no-new-privileges`, real Mongo and loopback HTTP |
| Restricted 200-record probe | 200 inert, encrypted synthetic records reviewed; aggregate health/reader counts **200**; all ciphertexts retained |
| Full host reader without actual account/call evidence | Correctly **incomplete**, not a fabricated live pass |
| Recorded duplicate in the restricted probe | Safety scope correctly **blocked**; one duplicate record, no new user clients, no call joins/leaves, no key/data deletion |
| Actual optional-watchdog exercise | No-network synthetic Docker fixture: starting skip, unhealthy dry-run, same-container restart with retained boot counter, cooldown and manually stopped service left stopped |
| Baseline protected bytes | **23** critical files byte-identical to 1.4.4, including encryption, session safety/lease/wire fencing, native ownership, plans/jobs/auto calls, UI/photo/runtime, dependency pins/Dockerfile/base Compose and original banner |
| Original banner SHA256 | `52add815ba014ae85fe1d50b9f73ce5eac85902485959586c4b70b0f993c9deb` |
| Archive integrity / privacy | Exact inventory, CRC, safe paths, local links, every manifest digest and supplied-log identifier exclusion checked during packaging |

The image-suite container imported **`/app/app/__init__.py`**, not the mounted checkout's application. Tests and deployment/documentation fixtures were mounted read-only at `/verification`, with `pythonpath=/app`. Root was used only for test dependency installation inside that disposable suite container. A separate runtime probe exercised the shipped UID-10001/read-only/no-capabilities configuration with no real Telegram access.

## Added 200-account and operational coverage

`tests/test_vps_200.py` and `tests/test_watchdog.py` add **65** cases, while the existing capacity assertions intentionally move from 100 to 200. Explicit custom host/customer limits of 20/100 remain valid.

- Finite pool and per-task account bounds through **200**, rejecting 201; original customer default 5, channel/business/rate/call-duration restrictions unchanged.
- Completion races for the last slot at **199 → 200**, keeping all 199 existing synthetic ciphertexts, with only one committed new authorization. Full-pool existing-account reauthentication remains possible.
- Finite 200 and independent account/channel unlimited modes; finite legacy 5/7/20/100 allowances do not expand, and renewal preserves paid choices.
- Exclusive **125 + 75** account reservations, no overlap, release/persistence and unchanged ciphers.
- All 200 identity checks/progress records, current per-account state reload, lock release between accounts and outside UI notifications, periodic/recovery coverage of account 200.
- 200-slot local shutdown and fleet duplicate containment retaining saved encrypted data, without logout of retained authorizations.
- Host reader preserves 200 reviewed/self-verified counts. Staff target correction cannot overlook busy automatic account **200** even when a session's cached assigned count is zero.
- Fair automatic **200 / 4 = 50 per channel** allocations and 60-account headroom for queued manual priority, preserving original call deadlines. RTC results here are synthetic.
- VPS resources/default overrides, fresh bundled/external setup command choice, hidden/private secrets, finite health budgets and original private key/owner/database/JSON preservation.
- Watchdog scope, explicit project validation, no shell interpolation, one-container requirement, starting/healthy/stopped/restarting cases, missing health, dry-run, sequential same-container restart, persisted 15-minute throttle, CLI-timeout throttle, project lock, state corruption/symlinks, sanitized errors and opt-in systemd units. A healthy safety-paused API is not restart approval.

All existing phone → OTP → exact optional 2FA / QR tests, roles, feature tiers, independent unlimited quotas, target permanence/corrections, required subscriptions, edited English smallcaps UI, original start photo, schedules/recovery, pacing/moderation, manual priority, transport cleanup and session-safety regressions remain in the suite.

## Real restricted HTTP / database observation

The separate disposable-container probe:

1. Checked UID 10001, read-only `/app`, absence of private `.env` / `config.json`, public defaults, ffmpeg and local SDK compatibility.
2. Created one uniquely named disposable Mongo database and 200 **inert encrypted strings, not Telegram authorizations**. Disabled records prevented any user client construction; attempted real Telegram/Bot API transports were explicitly forbidden.
3. Exercised actual `/health/live` and `/health/ready` startup/readiness/shutdown responses, private-chat mode's disabled browser routes, current server-clock singleton claim, background health export, and the actual read-only host reader.
4. Verified 200 reviewed/saved counts while saved-authorization and call proofs correctly stayed incomplete. Bot API identity was a controlled synthetic response, not a real bot connection.
5. Added a duplicate rejection marker to one existing record, observed fleet safety pause and blocked safety report, and verified **all 200 original ciphertexts stayed identical**. No user-account connections, OTPs, call joins/leaves or real duplicated authorizations were created.
6. Closed tasks/lifespan cleanly and removed only its uniquely named disposable database. No production database or volumes were touched.

## Reproduction and environmental retries

Full source command (use a disposable database only):

```sh
TEST_MONGO_URI=mongodb://127.0.0.1:27019 python -m pytest -q --maxfail=2
```

Image test shape:

```sh
# Inside an isolated test container of the already-built image, with read-only
# source fixtures at /verification and a fresh disposable Mongo per batch:
PYTHONPATH=/app:/verification/tests python -m pytest -q \
  -c /verification/pyproject.toml --rootdir=/verification \
  -o pythonpath=/app -p no:cacheprovider /verification/tests/TEST_FILE.py
```

The verifier collected the image's 706 unique node IDs, divided them into 90-case batches, launched each against fresh disposable Mongo, and required every batch to exit 0 with its exact expected pass count. No cases were skipped, deselected or counted twice. No application bytes changed between the source suite, final image and these checks.

**Earlier attempts are not counted as passes.** A disposable host Mongo initially inherited a 1,024-file limit and exhausted it. A source attempt overlapped the VFS image build; a later monolithic image run reached 634 passes before the approximately 2-GiB QA environment became unresponsive and Mongo timed out during its many temporary-database checkpoints. Those attempts were retained as failed/interrupted evidence, not described as successful runs. Final source verification used the raised file limit without a concurrent build; final image verification used isolated fresh-Mongo batches and a bounded test-resource guard. Test-only handle/periodic-checkpoint tuning was not added to production Compose. The 8-GiB production Mongo envelope serves the application's database, not hundreds of integration-test databases.

## Actual optional-watchdog Docker check

A separately labeled, **no-network** synthetic container ran a small signal-waiting Python process with an intentionally failing health command and a disposable bind-mounted boot counter. It contained no bot credentials, Mongo URI or Telegram client. The shipped host watchdog skipped the image startup grace, dry-ran the unhealthy state without restarting, requested one sequential restart of that same container, retained the counter at 2, honored the persisted cooldown, and left it stopped after an explicit manual stop. The fixture was then removed. Docker can return from restart before the program's first user-code instruction; the counter was verified after startup rather than treating the immediate race as an application defect. This is Docker-control verification, not a live bot/VPS failover test.

## Deployment and acceptance limits

Use [VPS_200.md](docs/VPS_200.md) for the correct bundled/external Mongo profile, **same original project identity**, private config/key/database/volume preservation, Docker daemon boot enablement, health checks and optional host watchdog. Restart policy alone does not act on a merely unhealthy running container. The watchdog is opt-in, never owner review, and must be stopped before deliberate maintenance to avoid an independent inspect/restart race.

No access to the user's VPS/provider/real Telegram accounts was available. Therefore no actual 200-account login/session longevity, simultaneous 200-RTC attendance, media quality, Telegram stability/no-ban/no-revocation, provider boot/failure recovery or permanent operation was certified. Finish [LIVE_ACCEPTANCE.md](docs/LIVE_ACCEPTANCE.md) and [HOST_VERIFICATION.md](docs/HOST_VERIFICATION.md) in stages on the one authorized host, returning only sanitized outcomes. Existing invalidated keys need authorized fresh login after conflicting copies stop; no automatic OTP, lease bypass or rejected-status reset was introduced.
