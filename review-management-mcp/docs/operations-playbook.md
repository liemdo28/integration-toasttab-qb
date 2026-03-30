# Operations Playbook (No-cost setup)

## Recommended direction (simple + effective)
1. Keep Google Reviews integration as primary automation source.
2. Use one runner script (`scripts/run-daily.mjs`) for deterministic daily/weekly jobs.
3. Keep `DRY_RUN=true` during first week.
4. Rotate Google keys if ever exposed in git history.

## Scheduler on Windows (Task Scheduler)
Create a scheduled task:
- Trigger: Daily 09:00 (or Weekly)
- Program/script: `C:\Program Files\nodejs\node.exe`
- Add arguments: `scripts/run-daily.mjs`
- Start in: `E:\Project\review-management-mcp`

Optional second trigger for weekly deep run.

## Scheduler on macOS (launchd, preferred over cron)
Create file `~/Library/LaunchAgents/com.review.automation.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>com.review.automation</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/local/bin/node</string>
      <string>/Users/<you>/review-management-mcp/scripts/run-daily.mjs</string>
    </array>
    <key>WorkingDirectory</key><string>/Users/<you>/review-management-mcp</string>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key><integer>9</integer>
      <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key><string>/Users/<you>/review-management-mcp/logs/launchd.out.log</string>
    <key>StandardErrorPath</key><string>/Users/<you>/review-management-mcp/logs/launchd.err.log</string>
  </dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.review.automation.plist
launchctl start com.review.automation
```

## Daily runner contract
`run-daily.mjs` executes:
1. `python3 scripts/review_management_runner.py`
2. `node scripts/notify-pending.mjs`

## Security checklist
- Never commit `.env`.
- Keep `.env.example` only.
- Store production secrets in OS env or secret manager.
- Rotate all keys if they were previously exposed.

