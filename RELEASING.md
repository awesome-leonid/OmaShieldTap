# Source release procedure

Version: **0.1.0**. Expected source basename:
`omarchy-remote-buttons-0.1.0`. This procedure creates local source artifacts; it
does not publish, install, update a live desktop, create a tag, or invent a
hosting identity.

## Before packaging

1. Review `SECURITY.md` and run the checks from `CONTRIBUTING.md`. Complete and
   record the separate native Omarchy/Wayland acceptance checks. Hosted CI cannot
   establish physical-button behavior, login/reboot persistence, or hardware
   coverage; explicitly record anything unverified.
2. Confirm the intended manifest identity `leo.remote-buttons`, version `0.1.0`,
   human credit Leo, and MIT license. Review the changelog and agent instructions.
3. Review and stage only the intended source (staging is a maintainer action):
   ```sh
   git status --short
   git diff --cached --check
   git diff --cached
   git ls-files --stage
   ```
   Stage new files deliberately before packaging. The helper requires
   `manifest.json`, `Panel.qml`, `Model.js`, `remote_buttons.py`, `README.md`,
   `LICENSE`, `agent/SKILL.md`, and `scripts/make-release.py`.
   It also allows the declared top-level documentation and source under
   `scripts/`, `tests/`, `i18n/`, `.github/`, `docs/`, and `agent/`.
4. Do not stage secrets, personal config, home paths, recordings, generated
   outputs, symlinks, submodules, or audio code/assets/binaries. `patches/` and
   `third_party/` are not release roots. The private `ARCHITECTURE.md` is always
   excluded, even if indexed. Unknown indexed paths are refused, not silently
   included. Remove accidental files from the index without deleting user data.

## Build and verify locally

```sh
python3 scripts/make-release.py --output dist
(cd dist && sha256sum --check SHA256SUMS)
tar -tzf dist/omarchy-remote-buttons-0.1.0.tar.gz
```

The helper returns JSON containing `ok`, `archive`, `sha256`, and `files`.
It reads a snapshot of stage-0 immutable index blobs with Git replace objects
disabled, including the manifest's version. It does not collect arbitrary
working-tree bytes. Visible unstaged tracked edits cause refusal; hidden edits
under index flags still cannot enter the archive. Review flags/attributes too.

Members are sorted, regular files only, with indexed executable modes,
zero timestamps/UIDs/GIDs, empty owner names, and a gzip header without a source
filename. Limits: 512 members, 4 MiB each, 16 MiB total source bytes. Text-only
and privacy checks supplement, not replace, human review. See `SECURITY.md` for
limits and the trusted-output-directory assumption.

Repeat the build and compare checksums in the same Python/zlib environment to
check reproducibility. Inspect archive members and their actual contents before
sharing. Confirm no absolute/machine-local paths, credentials, private config,
audio source, or generated artifacts slipped into approved source directories.
A source archive is not itself a committed Git repository; the native Omarchy
Git installer needs a reviewed local repository created from it (using the
maintainer's real Git identity) or an existing reviewed local checkout.

## CI and publication boundary

The workflow runs backend/stdlib, Node model, and release tests in an Arch Linux
container so the keymap tests use the same XKB format as Omarchy. It
checks generated Lua plus source Lua syntax when source files exist, then builds/checksums a source
artifact. Native Omarchy UI fixtures skip on hosted runners without Wayland and
the installed shell. No audio job exists. A workflow file is not evidence that
hosted CI has run.

Do not upload, tag, push, or claim publication until the maintainer explicitly
authorizes it and the actual remote target is known. Keep acceptance evidence
separate from the source archive; no private recordings or machine paths belong
in the release.
