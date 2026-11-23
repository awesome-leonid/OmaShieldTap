# OmaShieldTap

Remap Bluetooth remote buttons on Omarchy. The built-in preset is for the
2019 NVIDIA SHIELD remote. Version **0.1.0**, MIT.
The tray popup is a **read-only assignment cheat sheet**: button icons beside
short action labels, with physical names and full details available on hover.
Configure buttons
through the small **plugin CLI**, `omarchy-remote-buttons`, directly or by asking
the normal AI assistant you already use to run its documented commands. The
plugin saves assignments and the tray reflects them; it does not build or run
an agent. No new agent runtime, bot, MCP server, registration, provider account,
API key, network connection, root access, or background service is required.

There is no audio implementation: no Bluetooth microphone bridge, capture,
recordings, audio binaries, or audio build step. A command assignment may launch
an independently installed program; that program is not supplied by this plugin.

## Requirements and scope

- Linux running Omarchy's native Quickshell UI and Hyprland **Lua** configuration.
  Your active Hyprland config must load `hypr/bindings.lua` (as Omarchy's
  standard configuration does). A custom configuration must load it too.
- Python 3 with its standard library; Omarchy's native `libxkbcommon` for keymap
  compilation. No pip dependencies.
- One configured remote for this MVP. The built-in NVIDIA SHIELD 2019 preset has
  16 button records. Other hardware may need explicit source-key/button records
  through the JSON model; the preset is not evidence that every Bluetooth
  remote has been tested.

The backend owns a small Lua loader, a per-device XKB map, its JSON configuration,
and a user-bin wrapper. Assignments are scoped to the selected Hyprland keyboard;
it does not replace laptop shortcuts or globally unbind compositor shortcuts.
Conflicting reserved keys are refused rather than silently overriding bindings.

**Binding compatibility:** this MVP targets an audited desktop configuration
where each shortcut has one non-modifier key (plus any modifiers). Arbitrary
native multi-key chords are unsupported: this Hyprland version's inspection
output can hide their extra keys, so a visible-conflict scan cannot certify
those configurations as safe.

## Install

Review the source before enabling it: Omarchy plugins run as your user, without
a sandbox. Pair the remote through Omarchy's Bluetooth settings first.

```sh
omarchy plugin install https://github.com/awesome-leonid/OmaShieldTap.git --enable
```

To install a reviewed commit rather than the latest default branch, clone the
repository, check out that commit, and run `omarchy plugin install "$PWD" --enable`
from the checkout. The installer clones committed Git history, not local edits.
The internal plugin ID (`leo.remote-buttons`) and CLI name are unchanged so the
rebrand does not create a second plugin or move the existing configuration.

Plugin installation does not run backend setup. Inspect devices, then substitute
the exact keyboard `name` reported by `devices`:

```sh
python3 "$HOME/.config/omarchy/plugins/leo.remote-buttons/remote_buttons.py" devices
python3 "$HOME/.config/omarchy/plugins/leo.remote-buttons/remote_buttons.py" setup \
  --keyboard nvidia-shield-remote --name 'NVIDIA SHIELD Remote' \
  --acknowledge-single-key-bindings
```

The acknowledgment flag confirms that the desktop bindings were audited against
that single-nonmodifier-key requirement; do not add it blindly for custom native
chord configurations. `nvidia-shield-remote` is an example, not device
autodetection. Setup creates
`$HOME/.local/bin/omarchy-remote-buttons`; ensure that directory is on `PATH`.
Use **`omarchy-remote-buttons`**, not a presumed `omarchy remote-buttons` alias:
the packaged Omarchy dispatcher need not discover user-bin commands.

## Assign buttons

```sh
omarchy-remote-buttons schema
omarchy-remote-buttons agent-guide
omarchy-remote-buttons show
omarchy-remote-buttons bind center --key Return
omarchy-remote-buttons bind mic --command '["omarchy-dictation","toggle"]' --label 'Toggle dictation'
omarchy-remote-buttons bind center --shortcut 'CTRL + SHIFT + V'
omarchy-remote-buttons bind center --disabled
omarchy-remote-buttons unbind center
```

`unbind BUTTON` restores **native/passthrough** behavior; it does not disable the
button. Defaults assign center/OK to Return and mic to the external
`omarchy-dictation toggle` command. Other preset buttons remain native. Install
that external dictation program separately, replace the assignment, or unbind
mic; this plugin does not implement or install dictation.

Commands take a **JSON argv array**, never a raw shell string. Binding, reading
configuration, or opening the tray never executes the assigned action. Do not
put secrets in arguments: assignments are visible in `show` and may appear in
the tray. Use the called program's own credential storage instead. A
`shortcut` sends modifier/key events to the **focused application** and does not
necessarily invoke compositor desktop shortcuts. Use an explicit program argv
assignment when you need a desktop operation.

Normal command results and errors are JSON; help is text. Check exit status and
`ok`, then read back with `show`. `apply --json JSON` accepts a complete validated
configuration with the current revision for a batch update; do not submit an
old revision or an entire `show` response envelope. See `schema` and
`agent-guide` for the installed contract.

Changes validate the model, update managed configuration and input files,
reload Hyprland, and check compositor errors. Detected failures attempt rollback.
Configuration lives at
`${XDG_CONFIG_HOME:-$HOME/.config}/omarchy-remote-buttons/config.json`.

After a reinstall, pair the remote again, install OmaShieldTap, and run setup
for the keyboard name reported on that system. Keep personal mappings in a
separate private backup. If restoring them, use `schema`, `show`, and `apply`
to adapt the assignments to the new device and current revision; do not copy
the old generated Lua, keymap, or ownership state onto a fresh system.

## Agents, removal, and verification

Give your existing assistant this README, the output of `agent-guide`, or the
optional [agent/SKILL.md](agent/SKILL.md). These are plain text instructions,
not installation machinery. No agent
registration, discovery setup, or global AI configuration edits are needed.

Use `omarchy-remote-buttons remove` to remove backend-owned integration, then
manage the tray plugin separately with native `omarchy plugin` commands.
**Backend removal deletes saved assignments**; back them up privately first.
Stop and inspect ownership conflicts rather than force-deleting files.

### Recovery after an interrupted write

The transaction is not a crash-recovery journal. A power loss or forced kill
can leave an ownership mismatch. Before changing or removing the integration,
keep a private backup of your mappings and a known-good Hyprland config.
If a write is interrupted and ownership checks fail, do not delete the ownership
record or rerun setup over the partial state. Use a TTY if the desktop is
unusable. Back up the current files, then restore a consistent pre-operation
snapshot (including the plugin state and generated files, if present), keeping
any newer unrelated edits to `bindings.lua`. If you have no consistent snapshot,
restore your known-good Hyprland config without the plugin's marked loader block,
leave the partial plugin files backed up, and ask for help before reinstalling.

### Update on the same installation

For a Git-installed copy, update the tray plugin, review the updated source, then
refresh the backend from that source rather than running setup or remove:

```sh
omarchy plugin update leo.remote-buttons
python3 "$HOME/.config/omarchy/plugins/leo.remote-buttons/remote_buttons.py" refresh
omarchy-remote-buttons show
```

Refresh preserves the assignments and increments the revision. Back up the
wrapper, loader, generated Lua and XKB, config, and ownership state together before
updating. Refresh refuses a partial or modified installation rather than taking
ownership of unknown files.

## Verification

Run `python3 -m unittest discover -s tests -v` for automated checks (Node.js is
needed for model tests; `xkbcli` is used by keymap tests). Hosted CI skips native
UI fixtures without Omarchy/Wayland. A local native acceptance check is still
required: confirm the loaded tray updates after a reversible harmless mapping,
actual remote presses work, and the laptop's bindings remain unchanged. No
physical-hardware, login/reboot, or publication result is implied by these docs.

See [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), and
[RELEASING.md](RELEASING.md).
