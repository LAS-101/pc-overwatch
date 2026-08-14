# CPU Temperature Telegram Alert

A lightweight monitoring pipeline that checks CPU temperature on a schedule and sends a Telegram alert if it exceeds a defined threshold. Runs automatically in the background via `systemd`, starting on boot with no manual intervention required.

---

## How it works

```
systemd timer (every 5s)
        │
        ▼
cpu-alert.service (oneshot)
        │
        ▼
   `cpu` bash script
        │
        ├── reads CPU temp from /sys/class/thermal/thermal_zone*
        │
        └── if temp > THRESHOLD (89°C)
                    │
                    ▼
        telegram_msg.py <temp>
                    │
                    ▼
        Telegram Bot API → sends alert message
```

Each check is a **fresh, isolated run** — there's no long-running loop process sitting in memory. `systemd` handles the scheduling entirely, and each run starts, checks the temperature, optionally sends an alert, and exits cleanly.

---

## Files

| File | Purpose |
|---|---|
| `cpu` | Bash script — reads current CPU temp, compares against threshold, calls the Python alert script if exceeded |
| `telegram_msg.py` | Python script — sends a Telegram message via the Bot API; takes the temperature as a CLI argument |
| `config.py` | Stores `token_key` (bot token) and `chat_id` (your Telegram chat ID) |
| `~/.config/systemd/user/cpu-alert.service` | Defines *what* to run — a single execution of the `cpu` script |
| `~/.config/systemd/user/cpu-alert.timer` | Defines *when* to run it — every 5 seconds |

---

## Pipeline breakdown

### 1. `cpu` (bash script)
- Loops through `/sys/class/thermal/thermal_zone*` looking for the zone with type `x86_pkg_temp`
- Converts the raw millidegree reading to a plain integer (e.g. `52`)
- Logs the reading (`Current CPU temp: 52°C`) — visible in `journalctl`
- If temp exceeds `THRESHOLD` (currently `89`), calls:
  ```bash
  .venv/bin/python3 telegram_msg.py "$TEMP"
  ```

### 2. `telegram_msg.py`
- Takes the temperature as `sys.argv[1]`
- Builds an alert message and sends it via `telegram.Bot.send_message()`
- Uses `asyncio.run()` so each invocation cleanly opens and closes its own event loop — no lingering loop errors, since it's a short-lived process each time

### 3. `cpu-alert.service`
- `Type=oneshot` — runs once and exits, doesn't stay resident
- Sets `WorkingDirectory` so the script can find `config.py` and the venv correctly

### 4. `cpu-alert.timer`
- `OnBootSec=10s` — first run fires 10s after boot
- `OnUnitActiveSec=5s` — subsequent runs fire 5s after the previous one finishes
- `AccuracySec=1s` — keeps timing tight (systemd batches timers loosely by default)

---

## Setup summary

```bash
chmod +x ~/projects/cpu-temperature/cpu

# Enable and start the timer (not the service directly)
systemctl --user daemon-reload
systemctl --user enable --now cpu-alert.timer

# Let it run even before login (e.g. right after boot)
sudo loginctl enable-linger elyes
```

---

## Useful commands

**Status & scheduling**
```bash
systemctl --user list-timers                 # confirm the timer is active + see next run time
systemctl --user status cpu-alert.timer       # timer status
systemctl --user status cpu-alert.service     # last run status
```

**Logs**
```bash
journalctl --user -u cpu-alert.service -f     # live log of each temp check + alerts
journalctl --user -u cpu-alert.service -n 50  # last 50 log lines
```

**Manual control**
```bash
systemctl --user start cpu-alert.service      # manually trigger one check now (useful for testing)
systemctl --user stop cpu-alert.timer         # stop future scheduled runs
systemctl --user disable --now cpu-alert.timer # fully disable + stop
```

**After editing `cpu` or `telegram_msg.py`**
```bash
systemctl --user daemon-reload                # only needed if .service/.timer files changed
systemctl --user restart cpu-alert.timer      # not usually needed — oneshot services just re-run on schedule
```

---

## Testing the alert

Temps normally sit well under the threshold, so the Telegram branch won't fire on its own. To verify it works end-to-end:

1. Temporarily lower the threshold:
   ```bash
   nano ~/projects/cpu-temperature/cpu
   # change THRESHOLD=89 to THRESHOLD=30
   ```
2. Watch the logs:
   ```bash
   journalctl --user -u cpu-alert.service -f
   ```
3. Within ~5–10s you should see the `telegram_msg.py` call fire and receive the message on Telegram.
4. Set `THRESHOLD` back to `89` once confirmed.

---

## Getting your Telegram `chat_id`

1. Send your bot any message on Telegram.
2. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
3. Find `"chat": {"id": ...}` in the JSON response — that's your `chat_id`.
4. Add it to `config.py`:
   ```python
   chat_id = 123456789
   ```