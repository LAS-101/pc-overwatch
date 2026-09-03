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
│   ├── read_temp            # shared, side-effect-free CPU temp reader
│   ├── send_alert.py        # sends a one-off temperature alert message
│   ├── pc_notify.py         # sends boot/shutdown messages
│   ├── bot_listener.py      # long-running: listens for /status, replies with PC state + temp
│   └── config.py            # loads token_key, chat_id, PC_NAME, project_path from .env
├── systemd/
│   ├── cpu-alert.service    # runs `cpu` once
│   ├── cpu-alert.timer      # triggers cpu-alert.service every 5s
│   ├── pc-notify.service    # fires on boot (ExecStart) and shutdown (ExecStop)
│   └── bot-listener.service # keeps bot_listener.py running continuously
├── requirements.txt
├── README.md
├── .env                     # your real secrets — never committed (see .gitignore)
├── .env.example             # template showing what .env should contain
└── .gitignore
```

The `systemd/` folder holds the unit files as **templates** — they need to be copied into `~/.config/systemd/user/` to actually be picked up by systemd (see Setup below). All scripts that need to talk to Telegram, read config, or reference other project files live together in `scripts/`, including `config.py`.

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
│         ▼                    │                                          │   read_temp                    │
│   `cpu` bash script          │                                          │         │                       │
│    ├─ sources .env           │                                          │         ▼                       │
│    ├─ calls read_temp        │                                          │   reply_text(...)               │
│    └─ if temp > THRESHOLD ──►│── send_alert.py <temp> ─────────────────►│                                 │
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
| `scripts/cpu` | Bash script — sources `.env`, reads current CPU temp via `read_temp`, sends the Telegram alert if it exceeds the threshold |
| `scripts/read_temp` | Shared temperature reader — no side effects, safe to call from both `cpu` and `bot_listener.py`; uses no project paths at all, so it's fully portable as-is |
| `scripts/send_alert.py` | Sends a Telegram alert message; takes the temperature as a CLI argument |
| `scripts/pc_notify.py` | Sends a boot or shutdown message depending on the argument passed (`boot` / `shutdown`) |
| `scripts/bot_listener.py` | Long-running bot process — replies to `/status` with PC state + live temperature |
| `scripts/config.py` | Loads `token_key`, `chat_id`, `PC_NAME`, and `project_path` from `.env` using `python-dotenv` |
| `.env` | Your real secrets and local path — **never committed** |
| `.env.example` | Template showing which variables `.env` needs, with placeholder values |
| `systemd/cpu-alert.service` | Defines *what* to run — a single execution of `cpu` |
| `systemd/cpu-alert.timer` | Defines *when* to run it — every 5 seconds |
| `systemd/pc-notify.service` | Runs `pc_notify.py boot` on start, `pc_notify.py shutdown` on stop |
| `systemd/bot-listener.service` | Keeps `bot_listener.py` running continuously, auto-restarts on failure |

---

## Pipeline breakdown

### 1. `cpu` (bash script)
- Auto-detects its own location on disk and sources `.env` from the project root — no hardcoded path required to find `.env` itself
- Uses `project_path` (loaded from `.env`) to build the paths to `read_temp` and `send_alert.py`
- Calls `read_temp` to get the current CPU temperature as a plain integer (e.g. `52`)
- Logs the reading (`Current CPU temp: 52°C`) — visible in `journalctl`
- If temp exceeds `THRESHOLD` (currently `95`), calls:
  ```bash
  "${project_path}.venv/bin/python3" "${project_path}scripts/send_alert.py" "$TEMP"
  ```

### 2. `read_temp`
- Loops through `/sys/class/thermal/thermal_zone*` looking for the zone with type `x86_pkg_temp`
- Converts the raw millidegree reading to a plain integer and prints it
- Prints `-1` if no matching zone is found
- Has **no side effects** and references no project-specific paths — safe to call from anywhere, including from `bot_listener.py` on every `/status` request, without risk of triggering a duplicate alert, and fully portable without any `.env` dependency

### 3. `send_alert.py`
- Takes the temperature as `sys.argv[1]`
- Sends the alert via `telegram.Bot.send_message()`
- Uses `asyncio.run()` so each invocation cleanly opens and closes its own event loop — no lingering loop errors, since it's a short-lived process each time

### 4. `pc_notify.py`
- Takes `boot` or `shutdown` as `sys.argv[1]`
- Builds a message using `PC_NAME` from `config.py` (or the machine's hostname if unset) and sends it via Telegram
- Includes internal retry logic (a few attempts, a few seconds apart) to survive the brief window right after boot where the network may not have a working DNS resolver yet

### 5. `bot_listener.py`
- Runs `ApplicationBuilder().run_polling()`, holding an open connection to Telegram
- Registers a `CommandHandler` for `/status`
- On `/status`, checks the sender's `chat_id` matches yours (ignores anyone else), then calls `read_temp` (via `project_path` from `config.py`) and replies with the PC's state and current temperature

### 6. `config.py`
- Uses `python-dotenv` to locate and load `.env`
- Exposes `token_key`, `chat_id`, `PC_NAME`, and `project_path` as plain variables for the other scripts to import

### 7. `cpu-alert.service` / `cpu-alert.timer`
- `Type=oneshot` — runs once and exits, doesn't stay resident
- `OnBootSec=10s` — first run fires 10s after boot
- `OnUnitActiveSec=5s` — subsequent runs fire 5s after the previous one finishes
- `AccuracySec=1s` — keeps timing tight (systemd batches timers loosely by default)

### 8. `pc-notify.service`
- `Type=oneshot` + `RemainAfterExit=yes` — keeps the unit marked "active" after `ExecStart` finishes, so systemd knows to run `ExecStop` later at shutdown
- `Before=shutdown.target reboot.target halt.target` — ensures the shutdown message has a chance to send before the network goes down
- `ExecStartPre=/bin/sleep 10` + `Restart=on-failure` — extra buffer and retry in case the network isn't fully up yet right after boot (see Troubleshooting)

### 9. `bot-listener.service`
- `Type=simple` — a normal long-running process
- `Restart=always` / `RestartSec=10` — auto-recovers if it crashes or Telegram's API hiccups

---

## Setup

### 1. Configure your environment

```bash
cd ~/projects/pc-overwatch
cp .env.example .env
nano .env
```

Fill in your real values:
```bash
token_key=your-telegram-bot-token
chat_id=your-telegram-chat-id
PC_NAME=YourPCName
# absolute path to this project's root — MUST end with a trailing slash
project_path=/home/youruser/projects/pc-overwatch/
```

`.env` is listed in `.gitignore` and is never committed — only `.env.example` (with placeholder values) is tracked in git.

### 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Make the scripts executable

```bash
chmod +x scripts/cpu
chmod +x scripts/read_temp
```

### 4. Install the systemd units

The files under `systemd/` use `%h`, systemd's built-in specifier for your home directory — no manual editing needed as long as you clone the repo to `~/projects/pc-overwatch`. (If you clone it somewhere else, see the note below.)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/cpu-alert.service ~/.config/systemd/user/
cp systemd/cpu-alert.timer ~/.config/systemd/user/
cp systemd/pc-notify.service ~/.config/systemd/user/
cp systemd/bot-listener.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now cpu-alert.timer
systemctl --user enable --now pc-notify.service
systemctl --user enable --now bot-listener.service
```

### 5. Let everything run even before login

```bash
sudo loginctl enable-linger $(whoami)
```

> **Note on relocating the project:** `%h` only expands to your home directory, not the full project path. If you clone this repo somewhere other than `~/projects/pc-overwatch`, update the `projects/pc-overwatch` portion of `WorkingDirectory`/`ExecStart`/`ExecStop` in every file under `systemd/` before copying them over. This is separate from `.env`'s `project_path`, which the Python/bash scripts use internally — the two need to stay in sync.

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

**After editing a script**
```bash
# cpu, read_temp, send_alert.py, pc_notify.py, config.py: no restart needed for cpu-alert
# (each oneshot run re-reads the file fresh from disk on its next cycle)

systemctl --user restart bot-listener.service   # required — this process stays resident
                                                  # and won't see file changes until restarted
```

**After editing a `.service`/`.timer` file**
```bash
systemctl --user daemon-reload                  # required whenever a unit file itself changes
systemctl --user restart cpu-alert.timer
systemctl --user restart bot-listener.service
systemctl --user restart pc-notify.service
```

**Resource usage** (each oneshot run is negligible — typically a few MB of memory and well under 50ms of CPU time; `bot-listener` idles around 30–40MB while connected)
```bash
systemctl --user status cpu-alert.service       # shows Memory/CPU of the last run
/usr/bin/time -v ./scripts/cpu                  # detailed manual measurement of a single run
```

---

## Testing

**Temperature alert**
Temps normally sit well under the threshold, so the alert branch won't fire on its own.
1. Temporarily lower the threshold:
   ```bash
   nano scripts/cpu
   # change THRESHOLD=95 to THRESHOLD=30
   ```
2. Watch the logs:
   ```bash
   journalctl --user -u cpu-alert.service -f
   ```
3. Within ~5–10s you should see `send_alert.py` fire and receive the message on Telegram.
4. Set `THRESHOLD` back to `95` (or your preferred value) once confirmed. No restart needed — the next scheduled run picks up the change automatically.

You can also test `send_alert.py` in complete isolation, bypassing `cpu` entirely:
```bash
.venv/bin/python3 scripts/send_alert.py 99
```

**Boot/shutdown notification**
- Reboot the machine — you should get the "PC is now ON" message shortly after boot.
- To test the shutdown message without actually powering off:
  ```bash
  systemctl --user stop pc-notify.service
  ```
  This simulates the `ExecStop` trigger and should send the "shutting down" message.

**`/status` command**
- Send `/status` to your bot from Telegram. You should get a reply like:
  ```
  🟢 PC is ON
  🌡️ CPU temp: 49°C
  ```
- If nothing comes back, check `systemctl --user status bot-listener.service` — it should show `active (running)`, not `failed` or `activating (auto-restart)`.

---

## Troubleshooting

**Boot notification doesn't arrive**
The most common cause is a DNS/network race condition: `pc-notify.service` can start before Wi-Fi has fully associated and DNS is actually working, even though `network-online.target` reports "ready." Check for this specifically:
```bash
journalctl --user -u pc-notify.service -b
```
Look for `Temporary failure in name resolution` or a `NetworkError`/`ConnectError`. The `ExecStartPre=/bin/sleep 10` and `Restart=on-failure` settings in `pc-notify.service` are there specifically to absorb this — if it's still failing consistently, try increasing the sleep duration.

**`/status` doesn't reply, or `cpu-alert` never sends an alert**
Almost always a stale or incorrect path. Confirm `read_temp` and `send_alert.py` work when called manually:
```bash
./scripts/read_temp
.venv/bin/python3 scripts/send_alert.py 99
```
If either fails, double check `project_path` in `.env` is correct and ends with a trailing slash.

**General path issues after moving or renaming the project**
Search for any leftover hardcoded references to the project's old name or location:
```bash
grep -rln "<old-path-or-name>" . --exclude-dir=.venv --exclude-dir=__pycache__
```

---

## Getting your Telegram `chat_id`

1. Send your bot any message on Telegram.
2. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
3. Find `"chat": {"id": ...}` in the JSON response — that's your `chat_id`.
4. Add it to `.env`:
   ```bash
   chat_id=123456789
   ```

---

## Security note

`.env` contains your real bot token and chat ID and must never be committed. It's listed in `.gitignore` by default — double check before your first push:
```bash
git ls-files | grep .env      # should only show .env.example, never .env
```
If your token is ever accidentally exposed, revoke it immediately via **@BotFather** on Telegram (`/revoke` or `/token`) and generate a new one.