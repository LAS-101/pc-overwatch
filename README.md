# PC Overwatch

A lightweight monitoring and notification pipeline for your PC, delivered entirely through Telegram. It watches CPU temperature on a schedule, announces when the machine turns on or off, and answers a `/status` command on demand — all running automatically in the background via `systemd`, with no manual startup required.

---

## Features

1. **CPU temperature alerts** — checks the CPU temperature every 5 seconds and sends a Telegram message if it crosses a defined threshold.
2. **Boot/shutdown notifications** — sends a Telegram message when the PC turns on, and another when it shuts down.
3. **On-demand status check** — send `/status` to the bot at any time and it replies with confirmation the PC is on, plus the current CPU temperature.

---

## Project structure

```
pc-overwatch/
├── scripts/
│   ├── cpu                 # oneshot: reads temp, sends alert if over threshold
│   ├── read_temp.sh         # shared, side-effect-free CPU temp reader
│   ├── telegram_msg.py      # sends a one-off temperature alert message
│   ├── pc_notify.py         # sends boot/shutdown messages
│   ├── bot_listener.py      # long-running: listens for /status, replies with PC state + temp
│   └── config.py            # token_key, chat_id, optional PC_NAME
├── systemd/
│   ├── cpu-alert.service    # runs `cpu` once
│   ├── cpu-alert.timer      # triggers cpu-alert.service every 5s
│   ├── pc-notify.service    # fires on boot (ExecStart) and shutdown (ExecStop)
│   └── bot-listener.service # keeps bot_listener.py running continuously
├── requirements.txt
├── README.md
├── .env
└── .gitignore
```

The `systemd/` folder holds the unit files as **templates** — they need to be copied into `~/.config/systemd/user/` to actually be picked up by systemd (see Setup below). All scripts that need to talk to Telegram or read config live together in `scripts/`, including `config.py`, so their relative imports work without extra path handling.

---

## How it works

```
┌─────────────────────────────┐   ┌──────────────────────────────────┐   ┌───────────────────────────────┐
│   cpu-alert.timer (5s)       │   │   pc-notify.service               │   │   bot-listener.service         │
│         │                    │   │   (boot/shutdown lifecycle)       │   │   (always running)             │
│         ▼                    │   │         │                        │   │         │                       │
│   cpu-alert.service          │   │  ExecStart → pc_notify.py boot   │   │  listens for /status commands  │
│   (oneshot)                  │   │  ExecStop  → pc_notify.py shutdown│   │         │                       │
│         │                    │   └──────────────────────────────────┘   │         ▼                       │
│         ▼                    │                                          │   read_temp.sh                  │
│   `cpu` bash script          │                                          │         │                       │
│    ├─ calls read_temp.sh     │                                          │         ▼                       │
│    └─ if temp > THRESHOLD ──►│── telegram_msg.py <temp> ───────────────►│   reply_text(...)               │
└───────────────────────────────┘                                        └───────────────────────────────┘
                                              │
                                              ▼
                                     Telegram Bot API
                                              │
                                              ▼
                                        Your phone
```

Each of the three services is a different systemd pattern, chosen to match the nature of its task:

| Service | Task type | Pattern used |
|---|---|---|
| `cpu-alert` | Periodic check | `.timer` + `Type=oneshot` |
| `pc-notify` | One-time lifecycle event | `Type=oneshot` + `RemainAfterExit=yes` |
| `bot-listener` | Continuous listening | `Type=simple`, long-running, `Restart=always` |

The `cpu-alert` check is a **fresh, isolated run** every cycle — no long-running loop process sitting in memory between checks. `bot-listener` is the one exception that must stay resident, since Telegram bots work via long-polling: the process holds an open connection so it can react to `/status` instantly, rather than checking periodically.

---

## Files

| File | Purpose |
|---|---|
| `scripts/cpu` | Bash script — reads current CPU temp via `read_temp.sh`, sends the Telegram alert if it exceeds the threshold |
| `scripts/read_temp.sh` | Shared temperature reader — no side effects, safe to call from both `cpu` and `bot_listener.py` |
| `scripts/telegram_msg.py` | Sends a Telegram alert message; takes the temperature as a CLI argument |
| `scripts/pc_notify.py` | Sends a boot or shutdown message depending on the argument passed (`boot` / `shutdown`) |
| `scripts/bot_listener.py` | Long-running bot process — replies to `/status` with PC state + live temperature |
| `scripts/config.py` | Stores `token_key` (bot token), `chat_id` (your Telegram chat ID), and optional `PC_NAME` |
| `systemd/cpu-alert.service` | Defines *what* to run — a single execution of `cpu` |
| `systemd/cpu-alert.timer` | Defines *when* to run it — every 5 seconds |
| `systemd/pc-notify.service` | Runs `pc_notify.py boot` on start, `pc_notify.py shutdown` on stop |
| `systemd/bot-listener.service` | Keeps `bot_listener.py` running continuously, auto-restarts on failure |

---

## Pipeline breakdown

### 1. `cpu` (bash script)
- Calls `read_temp.sh` to get the current CPU temperature as a plain integer (e.g. `52`)
- Logs the reading (`Current CPU temp: 52°C`) — visible in `journalctl`
- If temp exceeds `THRESHOLD` (currently `95`), calls:
  ```bash
  .venv/bin/python3 scripts/telegram_msg.py "$TEMP"
  ```

### 2. `read_temp.sh`
- Loops through `/sys/class/thermal/thermal_zone*` looking for the zone with type `x86_pkg_temp`
- Converts the raw millidegree reading to a plain integer and prints it
- Prints `-1` if no matching zone is found
- Has **no side effects** — safe to call from anywhere, including from `bot_listener.py` on every `/status` request, without risk of triggering a duplicate alert

### 3. `telegram_msg.py`
- Takes the temperature as `sys.argv[1]`
- Sends the alert via `telegram.Bot.send_message()`
- Uses `asyncio.run()` so each invocation cleanly opens and closes its own event loop — no lingering loop errors, since it's a short-lived process each time

### 4. `pc_notify.py`
- Takes `boot` or `shutdown` as `sys.argv[1]`
- Builds a message using the machine's hostname (or `PC_NAME` from `config.py` if set) and sends it via Telegram

### 5. `bot_listener.py`
- Runs `ApplicationBuilder().run_polling()`, holding an open connection to Telegram
- Registers a `CommandHandler` for `/status`
- On `/status`, checks the sender's `chat_id` matches yours (ignores anyone else), then calls `read_temp.sh` and replies with the PC's state and current temperature

### 6. `cpu-alert.service` / `cpu-alert.timer`
- `Type=oneshot` — runs once and exits, doesn't stay resident
- `OnBootSec=10s` — first run fires 10s after boot
- `OnUnitActiveSec=5s` — subsequent runs fire 5s after the previous one finishes
- `AccuracySec=1s` — keeps timing tight (systemd batches timers loosely by default)

### 7. `pc-notify.service`
- `Type=oneshot` + `RemainAfterExit=yes` — keeps the unit marked "active" after `ExecStart` finishes, so systemd knows to run `ExecStop` later at shutdown
- `Before=shutdown.target reboot.target halt.target` — ensures the shutdown message has a chance to send before the network goes down

### 8. `bot-listener.service`
- `Type=simple` — a normal long-running process
- `Restart=always` / `RestartSec=10` — auto-recovers if it crashes or Telegram's API hiccups

---

## Setup

```bash
# 1. Make the scripts executable
chmod +x ~/projects/pc-overwatch/scripts/cpu
chmod +x ~/projects/pc-overwatch/scripts/read_temp.sh

# 2. Copy the unit files into systemd's user directory
mkdir -p ~/.config/systemd/user
cp ~/projects/pc-overwatch/systemd/cpu-alert.service ~/.config/systemd/user/
cp ~/projects/pc-overwatch/systemd/cpu-alert.timer ~/.config/systemd/user/
cp ~/projects/pc-overwatch/systemd/pc-notify.service ~/.config/systemd/user/
cp ~/projects/pc-overwatch/systemd/bot-listener.service ~/.config/systemd/user/

# 3. Reload systemd and enable everything
systemctl --user daemon-reload
systemctl --user enable --now cpu-alert.timer
systemctl --user enable --now pc-notify.service
systemctl --user enable --now bot-listener.service

# 4. Let everything run even before login (e.g. right after boot)
sudo loginctl enable-linger elyes
```

> **Note:** All four unit files use absolute paths (`WorkingDirectory`, `ExecStart`, `ExecStop`) pointing at `/home/elyes/projects/pc-overwatch/...`. If you clone this repo somewhere else, or under a different username, update those paths in every file under `systemd/` before copying them over.

---

## Useful commands

**Status & scheduling**
```bash
systemctl --user list-timers                   # confirm the timer is active + see next run time
systemctl --user status cpu-alert.timer         # timer status
systemctl --user status cpu-alert.service       # last run status
systemctl --user status pc-notify.service       # boot/shutdown service status
systemctl --user status bot-listener.service    # should show "active (running)"
```

**Logs**
```bash
journalctl --user -u cpu-alert.service -f       # live log of each temp check + alerts
journalctl --user -u bot-listener.service -f    # live log of /status requests
journalctl --user -u pc-notify.service -n 20    # last boot/shutdown notification attempts
journalctl --user -xeu <service-name>           # detailed error output after a failure
```

**Manual control**
```bash
systemctl --user start cpu-alert.service        # manually trigger one temp check now
systemctl --user stop cpu-alert.timer           # stop future scheduled checks
systemctl --user restart bot-listener.service   # restart the bot listener
systemctl --user disable --now <service-name>   # fully disable + stop any of the four
```

**After editing any script or `.service`/`.timer` file**
```bash
systemctl --user daemon-reload                  # required whenever a unit file changes
systemctl --user restart cpu-alert.timer
systemctl --user restart bot-listener.service
systemctl --user restart pc-notify.service
```

**Resource usage** (each oneshot run is negligible — typically a few MB of memory and well under 50ms of CPU time; `bot-listener` idles around 30–40MB while connected)
```bash
systemctl --user status cpu-alert.service                     # shows Memory/CPU of the last run
/usr/bin/time -v ~/projects/pc-overwatch/scripts/cpu           # detailed manual measurement of a single run
```

---

## Testing

**Temperature alert**
Temps normally sit well under the threshold, so the alert branch won't fire on its own.
1. Temporarily lower the threshold:
   ```bash
   nano ~/projects/pc-overwatch/scripts/cpu
   # change THRESHOLD=95 to THRESHOLD=30
   ```
2. Watch the logs:
   ```bash
   journalctl --user -u cpu-alert.service -f
   ```
3. Within ~5–10s you should see `telegram_msg.py` fire and receive the message on Telegram.
4. Set `THRESHOLD` back to `95` (or your preferred value) once confirmed.

**Boot/shutdown notification**
- Reboot the machine — you should get the "PC is now ON" message shortly after login.
- To test the shutdown message without actually powering off:
  ```bash
  systemctl --user stop pc-notify.service
  ```
  This simulates the `ExecStop` trigger and should send the "shutting down" message immediately.

**`/status` command**
- Send `/status` to your bot from Telegram. You should get a reply like:
  ```
  🟢 PC is ON
  🌡️ CPU temp: 49°C
  ```
- If nothing comes back, check `systemctl --user status bot-listener.service` — it should show `active (running)`, not `failed` or `activating (auto-restart)`.

---

## Getting your Telegram `chat_id`

1. Send your bot any message on Telegram.
2. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
3. Find `"chat": {"id": ...}` in the JSON response — that's your `chat_id`.
4. Add it to `scripts/config.py`:
   ```python
   token_key = "your-bot-token"
   chat_id = 123456789
   PC_NAME = "Elyes-Fedora-Laptop"  # optional, defaults to the machine's hostname if omitted
   ```

---

## Notes on renaming or relocating the project

If you move this project to a different path or clone it fresh elsewhere, remember these three places all contain hardcoded absolute paths and need updating together:
1. Every file in `systemd/` (`WorkingDirectory`, `ExecStart`, `ExecStop`)
2. Inside `scripts/cpu` — the calls to `read_temp.sh` and `telegram_msg.py`
3. Inside `scripts/bot_listener.py` — the `READ_TEMP_SCRIPT` path variable

A quick way to catch every reference in one pass (excluding the venv, which has its own separate, harmless internal paths):
```bash
grep -rl "<old-path-or-name>" ~/projects/pc-overwatch --exclude-dir=.venv --exclude-dir=__pycache__
```