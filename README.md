# SSA Reddit Monitor

Automated Reddit mention tracker for [Superior Shrimp & Aquatics](https://superiorshrimpaquatics.com). Scans Reddit every 2 hours, fires Windows toast notifications on new mentions, and displays results in a desktop dashboard.

## Features

- **Desktop dashboard** — dark-themed tkinter UI with filtering (Direct SSA, Negative, Positive, My Posts), live search, and color-coded sentiment
- **Toast notifications** — Windows 10/11 alerts on new mentions; click to open the dashboard
- **Change detection** — persists seen IDs between runs so you only get alerted on new results
- **Scheduled scanning** — runs every 2 hours via Windows Task Scheduler, including on reboot
- **Sentiment detection** — flags negative keywords (DOA, scam, refund, etc.) in red
- **Thread fetchers** — manual scripts for deep-scanning known SSA comment threads

## Files

| File | Purpose |
|---|---|
| `ssa_notify.py` | Core scanner — searches Reddit, detects new mentions, fires toast |
| `ssa_dashboard.py` | Desktop UI — browse and filter all results |
| `ssa_fetch_threads.py` | Manual fetch of known negative threads |
| `ssa_fetch_threads2.py` | Manual fetch of additional historical threads |
| `test_ssa.py` | 30 pytest tests covering all pure functions |

## Setup

**Requirements:** Python 3.10+, Windows 10/11. No third-party packages needed for the monitor — only stdlib.

```
# Clone
git clone https://github.com/Djester808/ssa-reddit-monitor
cd ssa-reddit-monitor

# Run the dashboard
python ssa_dashboard.py

# Run a manual scan
python ssa_notify.py
```

**Schedule automated scans (every 2 hours + on login):**

```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NonInteractive -WindowStyle Hidden -Command `"& python.exe ssa_notify.py`""
$trigger = @(
  New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 2) -Once -At (Get-Date),
  New-ScheduledTaskTrigger -AtLogOn
)
Register-ScheduledTask -TaskName "SSA Reddit Monitor" -Action $action -Trigger $trigger `
  -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries)
```

## How It Works

1. `ssa_notify.py` queries the Reddit public JSON API for ~15 search terms (exact brand name, username, abbreviations scoped to aquarium subreddits)
2. New result IDs are compared against `seen_ids.json`; only unseen items trigger a notification
3. All results are written to `results_latest.json` which the dashboard reads
4. The dashboard auto-refreshes every 60 seconds; toast clicks open it via a registered `ssa-monitor://` URI protocol

## Running Tests

```
pip install pytest
pytest test_ssa.py -v
```
