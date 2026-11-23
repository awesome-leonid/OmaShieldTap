---
name: omarchy-remote-buttons
description: Configure device-scoped remote button assignments.
version: 0.1.0
author: Leo
license: MIT
platforms: [linux]
---

# Remote button assignments

Configure the button-only Omarchy plugin through its JSON CLI. The tray is a
read-only cheat sheet. No provider account, API, network, service, or audio
implementation is needed.

## When to use

- Inspect, assign, disable, or restore buttons on the user's configured remote.
- Set up one explicitly identified remote on Omarchy's Hyprland Lua desktop.
- Do not use for recording, microphone setup, general keyboard remapping, or
  changing global agent/provider configuration.

## Prerequisites

Linux with Omarchy, Python 3 stdlib, and native libxkbcommon/Hyprland Lua support.
The reviewed plugin must be installed; its backend setup creates the direct
`omarchy-remote-buttons` user-bin command. This optional file is plain instructions
for the assistant the user already uses, not a new agent product. No skill
installation, registration, discovery setup, MCP server, or global AI config
change is needed; the user can simply give their assistant this text.

## How to run

Invoke commands with your agent's terminal execution tool, for example
`terminal(command="omarchy-remote-buttons schema")`. The tool name may differ
between agents; these are ordinary process invocations, not provider APIs.
Before the wrapper exists, invoke `python3 remote_buttons.py` from the reviewed
installed plugin directory. Do not assume an `omarchy remote-buttons` alias.

## Quick reference

```sh
omarchy-remote-buttons --help
omarchy-remote-buttons agent-guide
omarchy-remote-buttons schema
omarchy-remote-buttons devices
omarchy-remote-buttons show
omarchy-remote-buttons setup --keyboard nvidia-shield-remote --name 'NVIDIA SHIELD Remote' --acknowledge-single-key-bindings
omarchy-remote-buttons bind center --key Return
omarchy-remote-buttons bind mic --command '["omarchy-dictation","toggle"]' --label 'Toggle dictation'
omarchy-remote-buttons bind center --shortcut 'CTRL + SHIFT + V'
omarchy-remote-buttons bind center --disabled
omarchy-remote-buttons unbind center
omarchy-remote-buttons remove
```

## Procedure

1. Read `agent-guide`, `schema`, `devices`, and `show`. Confirm the target and
   existing assignments; a missing configuration means setup is needed.
2. Obtain authorization for changes. If setup is needed, use the exact device
   `name` returned by `devices`, not the illustrative name above. Ask if device
   identity is uncertain. Audit the desktop's single-nonmodifier-key binding
   subset before adding `--acknowledge-single-key-bindings`; never use that flag
   to dismiss unknown custom chords. Only one configured remote is supported.
3. Use `bind`/`unbind` for individual changes. For an atomic batch, obtain a fresh
   `show` response, modify its `config` object, preserve the current revision,
   then send the complete object using `apply --json JSON`. Reject stale revisions
   rather than overwriting another change. Never write live JSON/Lua/XKB directly.
4. Check both process exit status and JSON `ok`; on failure report the actual
   error. Do not work around conflicts by globally unbinding keys.
5. Read `show` again and compare the requested button/action exactly. Confirm the
   loaded tray updates, without executing any command to test the view. Request
   permission before a physical press that could have side effects.

## Pitfalls

- A command is a JSON string array such as `["program","arg"]`, not shell text.
  Do not introduce `sh -c` around user input. Rendering/assignment must not run it.
- A shortcut sends keys to the focused application and may not trigger compositor
  shortcuts. For a desktop operation, prefer an explicit program argv assignment.
- `unbind BUTTON` restores native/passthrough behavior; it is not disable.
- The mic default calls independently installed `omarchy-dictation toggle`.
  This plugin contains no dictation/audio implementation; change or unbind it if
  that external program is unavailable.
- The Shield preset has 16 records; it does not establish compatibility with all
  Bluetooth remotes. Source-key records for different hardware need validation.
- Desktop bindings must use the audited single-nonmodifier-key subset (modifiers
  are allowed). Arbitrary native multi-key chords are unsupported because
  Hyprland inspection output can hide their extra keys; do not claim a scan
  proves those configurations safe.
- Removal only removes owned integration. Stop on ownership conflicts; do not
  erase unrelated edits. Manage the native tray plugin separately.

## Verification

Success requires fresh JSON read-back and the read-only tray reflecting the
assignment. Configuration changes validate/reload and roll back on failure.
Automated tests alone do not prove physical presses, login/reboot persistence,
or hardware coverage; explicitly distinguish what was actually checked.
