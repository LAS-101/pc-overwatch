# CPU Temperature Telegram Alert

A lightweight monitoring pipeline that checks CPU temperature on a schedule and sends a Telegram alert if it exceeds a defined threshold. Runs automatically in the background via `systemd`, starting on boot with no manual intervention required.

---

## Project structure

```
cpu-temperature/
├── cpu                     # main bash script (temp check + threshold logic)
├── telegram_msg.py         # sends the Telegram alert
├── config.py               # token_key + chat_id
├── requirements.txt
├── README.md
├── .env
├── .gitignore
└── systemd/
    ├── cpu-alert.service
    └── cpu-alert.timer
```

The `systemd/` folder holds the two unit files as **templates** — they need to be copied into `~/.config/systemd/user/` to actually be picked up by systemd (see Setup below).

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
| `systemd/cpu-alert.service` | Defines *what* to run — a single execution of the `cpu` script |
| `systemd/cpu-alert.timer` | Defines *when* to run it — every 5 seconds |

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

## Setup

```bash
# 1. Make the script executable
chmod +x ~/projects/cpu-temperature/cpu

# 2. Copy the unit files into systemd's user directory
mkdir -p ~/.config/systemd/user
cp ~/projects/cpu-temperature/systemd/cpu-alert.service ~/.config/systemd/user/
cp ~/projects/cpu-temperature/systemd/cpu-alert.timer ~/.config/systemd/user/

# 3. Reload systemd and enable the timer (not the service directly)
systemctl --user daemon-reload
systemctl --user enable --now cpu-alert.timer

# 4. Let it run even before login (e.g. right after boot)
sudo loginctl enable-linger elyes
```

> **Note:** `cpu-alert.service` references an absolute path (`WorkingDirectory` / `ExecStart`) pointing at the project directory and venv. If you clone this repo somewhere other than `~/projects/cpu-temperature`, update those paths in `systemd/cpu-alert.service` before copying it over.

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

**Resource usage** (each run is a short-lived oneshot process — negligible footprint, typically a few MB of memory and well under 50ms of CPU time)
```bash
systemctl --user status cpu-alert.service     # shows Memory/CPU of the last run (with accounting enabled)
/usr/bin/time -v ~/projects/cpu-temperature/cpu  # detailed manual measurement of a single run
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