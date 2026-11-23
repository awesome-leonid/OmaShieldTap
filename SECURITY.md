# Security

## Trust boundary

Omarchy plugins and user-authorized command assignments execute as the logged-in
user. They are not sandboxed. Review the installed source and every executable
argv assignment before enabling them. No root access, daemon, provider account,
API key, or network connection is required by this plugin.

The tray is read-only: plain-text assignment display, no command execution,
configuration editor, network calls, or audio subsystem. An external command
such as `omarchy-dictation toggle` is a separate program and has its own trust
boundary. Assigning it does not install or run it.

## Configuration safeguards

- The CLI accepts bounded, schema-validated JSON and a command **argv array**, not
  a raw shell command. An explicit `sh -c` assignment would still invoke a shell;
  argv validation is not an executable allowlist or command sandbox. The
  revision-checked dispatcher does not authenticate a physical press; the same
  local user can call it directly. Never put secrets in command arguments.
- Owned JSON/Lua/per-device XKB and the wrapper are changed through a transaction:
  validation, compositor reload/error checks, then publication. Detected failures
  attempt rollback; power loss and forced termination can leave a partial
  transaction. See the README's recovery section.
- Device-specific routing and reserved-symbol conflict checks avoid silently
  replacing laptop/global shortcuts. Do not bypass a conflict by globally
  unbinding existing keys. Native/unbound remote buttons retain native behavior.
- The supported desktop subset has one non-modifier key per binding, with
  optional modifiers. Hyprland's current inspection output omits parts of
  arbitrary native multi-key chords; visible-key conflict checks cannot certify
  those unsupported configurations. Do not present them as universally safe.
- Ownership records limit removal to plugin-owned integration. Modified owned
  files or unexpected links must be inspected rather than force-deleted.
- Treat keyboard names, labels, action summaries, and config as untrusted input.
  Do not render rich text or execute commands during display/assignment.

Use the supported CLI rather than editing live generated files. Keep a known
working desktop session available when testing input configuration. Physical
buttons can still have side effects through native behavior or assigned programs.

## Source releases

`scripts/make-release.py` snapshots stage-0 Git index object IDs and reads those
immutable objects with Git replacement objects disabled. Both the manifest
version and member bytes come from the index. Visible unstaged tracked changes
are refused; assume-unchanged/skip-worktree flags cannot substitute worktree
content. Untracked files are not packaged.

Only the declared source roots are accepted. The private `ARCHITECTURE.md` is
excluded. Symlinks, submodules, conflict stages, unsafe names, generated/private
paths, known audio paths/extensions, binary/non-UTF-8 content, home-directory
paths, and common private-key/token markers are refused. Limits are 512 source
files, 4 MiB per blob, and 16 MiB total uncompressed source content. Output links
are refused; final files use temporary files and atomic replacement.

These checks are defense in depth, **not a complete secret scanner** or proof that
arbitrary staged text is safe. Review the staged contents and archive manually.
Do not run a release from an attacker-controlled checkout or into an
attacker-writable output directory. Archive/checksum publication is not a single
two-file filesystem transaction; verify `SHA256SUMS` after building. Deterministic
bytes are expected for repeated builds in the same Python/zlib environment;
compression-library changes can change gzip bytes.

## Reporting

Do not post credentials, personal configuration, raw home paths, or recordings in
public reports. For a sensitive issue, use a private maintainer contact supplied
with the trusted distribution; no security mailbox or hosting URL is asserted
here. If none is available, request a private reporting channel without posting
exploit details or secrets. Include the version, a minimal sanitized reproducer,
and which verification was actually performed.
