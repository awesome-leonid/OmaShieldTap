# Contributing

OmaShieldTap is by Leo, MIT, version 0.1.0. Keep it button-only,
configurable by the user's existing assistant, and dependency-light: Python stdlib plus Omarchy's native
libxkbcommon, Hyprland Lua, and Quickshell. There is no audio build or service.

## Scope and workflow

- The tray is a read-only assignment cheat sheet. No GUI configuration controls,
  action-execution buttons, periodic busy refresh, or provider-specific setup.
- Preserve device-scoped behavior, laptop/native shortcuts, transaction rollback,
  and ownership-aware removal. Commands are argv arrays, not raw shell strings.
- Keep one configured remote for the MVP. The Shield preset has 16 records;
  distinguish supported data models from hardware actually tested.
- Use a vertical TDD loop: write one failing behavior, observe the expected
  failure, implement the smallest change, and rerun the tests. Add a failing
  regression before each new security guard.
- Develop inside the checkout with private HOME/XDG fixtures and fake desktop
  commands. Never modify the live desktop as an incidental test step.
- Do not add global Claude/Codex/Hermes configuration. Keep portable instructions
  in the README, `agent/SKILL.md`, and the backend's `agent-guide`.

## Automated checks

```sh
python3 -m unittest discover -s tests -p test_backend.py -v
python3 -m unittest discover -s tests -p test_ui.py -v
python3 -m unittest discover -s tests -p test_release.py -v
```

The suite uses stdlib unittest. Model tests also need Node.js. Backend keymap
verification uses native libxkbcommon and `xkbcli`; Lua syntax checks require
`luac` (Lua 5.4). Release tests create fresh temporary Git repositories and do
not contact a network or alter this checkout's index.

On Ubuntu 24.04 CI, native dependencies are installed with
`libxkbcommon0 libxkbcommon-tools xkb-data lua5.4 nodejs`. Desktop calls are faked
in backend tests; this is not a simulated claim that the actual compositor ran.

Native Qt/Quickshell fixtures require the installed Omarchy shell and Wayland;
otherwise they skip explicitly. Their windows stay hidden and they must not
execute assignments or write live state. Passing hosted CI is not local desktop
acceptance.

## Local acceptance (required before release)

With explicit permission on an Omarchy desktop, verify the actual loaded tray,
a reversible harmless mapping, real remote presses, and unchanged laptop/global
shortcuts. Verify failed reload rollback and removal preserve unrelated edits.
Record commands, outcomes, skips, and hardware identity. Do not claim physical,
login/reboot, or publication checks unless actually performed.

Review `SECURITY.md` and follow `RELEASING.md` for source packaging. No release
should include private configuration, recordings, binary payloads, home paths,
legacy bridge sources, patches, or vendored audio code.
