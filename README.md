# Window Switcher

A lightweight Windows utility that randomly switches between open application windows at configurable intervals, simulating Alt+Tab behavior. Keeps your screen looking active when you're away from the keyboard.

> 🟢 **Pure Python standard library — zero dependencies, no pip install required.**

## Features

- **Random window switching** — switches between visible application windows at random intervals
- **Burst mode** — occasionally performs 2–3 rapid switches to mimic real user behavior
- **Idle detection** — skips switching if mouse or keyboard activity is detected recently
- **Daily auto-stop** — automatically stops switching at a configurable time (default: 6:00 PM)
- **System tray icon** — green when active, gray when stopped
- **Single instance** — prevents multiple copies from running simultaneously
- **Silent background operation** — no console window when launched normally

## System Requirements

| Requirement | Details |
|---|---|
| **OS** | Windows 10 (version 1809+) / Windows 11 |
| **Python** | Python 3.8 or newer |
| **Dependencies** | None (standard library only) |
| **Architecture** | 64-bit (x64) or 32-bit (x86) |

## Quick Start

### Method 1 — Double-click (recommended)
Double-click **`启动.bat`** — the switcher will start silently and appear in the system tray.

### Method 2 — Debug mode
Double-click **`调试启动.bat`** — launches with a visible console to show errors and status messages.

### Method 3 — Command line
```bash
pythonw window_switcher.pyw
```

## Usage

### Tray Icon
| Action | Behavior |
|---|---|
| **Left-click** icon | Switch windows immediately |
| **Right-click** icon | Open control menu |

### Right-click Menu
| Menu Item | Description |
|---|---|
| ▶ Start Switching | Begin periodic window switching |
| ⏹ Stop Switching | Pause switching |
| 🔄 Switch Now | Perform one immediate switch |
| ⚙ Settings... | Configure intervals, idle detection, auto-stop |
| ❌ Exit | Quit the application |

### Icon Colors
- 🟢 **Green** — switching is active
- ⚪ **Gray** — switching is stopped

## Configuration

Settings are stored in `switcher_config.json` in the same directory as the script. Edit directly or use the Settings menu.

| Parameter | Default | Range | Description |
|---|---|---|---|
| `min_interval` | 120 | 10–3600 | Minimum seconds between switches |
| `max_interval` | 300 | 10–3600 | Maximum seconds between switches |
| `burst_enabled` | true | true/false | Enable rapid consecutive switches |
| `burst_chance` | 0.15 | 0–1 | Probability of burst mode per cycle |
| `idle_threshold` | 60 | 0–600 | Skip switch if user active within N seconds (0=off) |
| `auto_stop_time` | "18:00" | "HH:MM" or "" | Daily auto-stop time (empty=off) |

### Example Configuration
```json
{
  "min_interval": 120,
  "max_interval": 300,
  "burst_enabled": true,
  "burst_chance": 0.15,
  "idle_threshold": 60,
  "auto_stop_time": "18:00"
}
```

## Auto-start with Windows

1. Press `Win + R`, type `shell:startup`, press Enter
2. Create a shortcut to `启动.bat` in the startup folder
3. The switcher will launch automatically on login

## How It Works

### Window Switching
- Enumerates all visible top-level windows via `EnumWindows`
- Filters out invisible, cloaked (UWP), and empty-title windows
- Uses `AttachThreadInput` to bypass Windows foreground lock restrictions
- Selects a random target window and brings it to the foreground

### Idle Detection
- Uses `GetLastInputInfo` to check time since last user input (keyboard/mouse)
- If the user has been active within the idle threshold, the switch is skipped
- Ensures switching only happens when you're actually away

### Auto-stop
- Checks system time before each switch cycle
- When the configured stop time is reached, switching stops automatically
- Uses date tracking to prevent duplicate triggers within the same day

## Security

- **No network access** — runs entirely offline
- **No file system access** beyond reading/writing the config file in its own directory
- **No system modifications** — only uses standard Windows APIs
- **No compiled binaries** — pure Python script, fully auditable source code
- **No data collection** — nothing is logged, tracked, or transmitted

## FAQ

**Q: Why doesn't the icon appear after launching?**
A: The icon may be hidden in the system tray overflow area. Click the `^` arrow in the taskbar to find it, then drag it to the visible tray area.

**Q: Does this trigger antivirus software?**
A: No. The script uses only standard Windows APIs and contains no compiled executables, downloads, or system modifications.

**Q: How do I change the switching frequency?**
A: Right-click the tray icon → Settings, or edit `switcher_config.json` directly.

**Q: Can I make it stop at 5 PM instead of 6 PM?**
A: Yes. Open Settings and change the auto-stop time to `17:00`, or edit the config file.

**Q: Does it work on Windows 11?**
A: Yes. Windows 10 and 11 are both fully supported.

## Compliance Notice

This tool is intended **solely** for legitimate personal office scenarios, such as:
- Keeping your session active when briefly stepping away from your desk
- Maintaining system availability during offline tasks

**Strictly prohibited** uses include (but are not limited to):
- Game botting / automated farming scripts
- Circumventing corporate attendance tracking or desktop security controls
- Batch automation to bypass system restrictions

Any account bans, corporate disciplinary actions, or legal liabilities resulting from misuse are the **sole responsibility of the user**. The author assumes no liability for any unauthorized or illegal use of this software.

## License

MIT
