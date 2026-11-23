#!/usr/bin/env python3
"""Build a deterministic, button-only source archive from reviewed Git index blobs."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile


MAX_BLOB_BYTES = 4 * 1024 * 1024
MAX_FILES = 512
MAX_TOTAL_BYTES = 16 * 1024 * 1024

TOP_FILES = {"manifest.json", "Panel.qml", "Model.js", "remote_buttons.py", "README.md", "LICENSE",
             "AGENTS.md", "SECURITY.md", "CONTRIBUTING.md", "RELEASING.md", "CHANGELOG.md",
             ".gitignore", ".gitattributes"}
DIRECTORIES = {"scripts", "tests", "i18n", ".github", "docs", "agent"}
REQUIRED = {"manifest.json", "Panel.qml", "Model.js", "remote_buttons.py", "README.md", "LICENSE",
            "agent/SKILL.md", "scripts/make-release.py"}

FORBIDDEN_PARTS = {".git", "__pycache__", ".venv", "venv", "build", "dist", "target", ".cache",
                   ".pytest_cache", "node_modules", "credentials", "credentials.txt", "config.json",
                   "config.local.json", "id_rsa", "id_ed25519"}
FORBIDDEN_SUFFIXES = (".pyc", ".wav", ".pcm", ".raw", ".mp3", ".flac", ".ogg", ".m4a", ".aac",
                      ".log", ".tar.gz", ".zip", ".sha256", ".pem", ".key", ".so", ".o", ".a", ".exe")
AUDIO_NAME = re.compile(r"audio|atvvoice|bridge|recording|capture", re.IGNORECASE)
PRIVATE_CONTENT = re.compile(rb"/(?:(?:home|Users)/[^/\s\"']+|root)/|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")


def git(root, *args):
    return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=root, stderr=subprocess.PIPE)


def indexed_bytes(root, blob):
    size = int(git(root, "cat-file", "-s", blob))
    if not 0 <= size <= MAX_BLOB_BYTES:
        raise ValueError("Refusing oversized indexed source blob")
    data = git(root, "cat-file", "blob", blob)
    if len(data) != size:
        raise ValueError("Indexed blob size mismatch")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Refusing non-text source content") from exc
    if any(byte < 32 and byte not in {9, 10, 13} for byte in data) or PRIVATE_CONTENT.search(data):
        raise ValueError("Refusing binary/private source content (home path or credential marker)")
    return data


def package(root, output):
    files = []
    for row in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if row:
            metadata, name = row.split(b"\t", 1)
            mode, blob, stage = metadata.decode().split()
            name = name.decode("utf-8")
            if mode not in {"100644", "100755"} or stage != "0":
                raise ValueError(f"Refusing nonregular or conflicted indexed entry: {name}")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", name) or any(
                    part in {".", ".."} for part in name.split("/")):
                raise ValueError(f"Refusing unsafe indexed path: {name!r}")
            if name == "ARCHITECTURE.md":
                continue
            if not (name in TOP_FILES or "/" in name and name.split("/", 1)[0] in DIRECTORIES):
                raise ValueError(f"Refusing unexpected release file: {name}")
            parts = name.lower().split("/")
            if (any(part in FORBIDDEN_PARTS or part == ".env" or part.startswith(".env.") for part in parts)
                    or name.lower().endswith(FORBIDDEN_SUFFIXES) or AUDIO_NAME.search(name)):
                raise ValueError(f"Refusing private/generated/audio release path: {name}")
            files.append((name, mode, blob))
    missing = REQUIRED - {name for name, _, _ in files}
    if missing:
        raise ValueError("Missing required staged release files: " + ", ".join(sorted(missing)))
    files.sort()
    changes = subprocess.run(["git", "--no-replace-objects", "diff", "--quiet", "--no-ext-diff", "--no-textconv", "--"], cwd=root)
    if changes.returncode:
        raise ValueError("Refusing unstaged source changes; review and stage the intended release first")
    if len(files) > MAX_FILES:
        raise ValueError("Refusing excessive release entry count")
    total = 0
    for name, _, blob in files:
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", blob):
            raise ValueError(f"Invalid indexed blob identifier: {name}")
        size = int(git(root, "cat-file", "-s", blob))
        if not 0 <= size <= MAX_BLOB_BYTES:
            raise ValueError(f"Refusing oversized indexed source blob: {name}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Refusing excessive total indexed source size")
    manifest = next(blob for name, _, blob in files if name == "manifest.json")
    metadata = json.loads(indexed_bytes(root, manifest))
    if not isinstance(metadata, dict) or metadata.get("id") != "leo.remote-buttons":
        raise ValueError("Invalid release manifest identity")
    version = metadata.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version):
        raise ValueError("Invalid release manifest version; expected numeric major.minor.patch")
    base = "omarchy-remote-buttons-" + version
    for path in (output, *output.parents):
        if path.is_symlink():
            raise ValueError("Refusing symlinked output directory")
    archive = output / (base + ".tar.gz")
    checksum_path = output / "SHA256SUMS"
    if archive.is_symlink() or checksum_path.is_symlink():
        raise ValueError("Refusing symlinked release output")
    output.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".release-", dir=output)
    try:
        with os.fdopen(fd, "wb") as destination:
            with gzip.GzipFile(filename="", mode="wb", fileobj=destination, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as tar:
                    for name, mode, blob in files:
                        data = indexed_bytes(root, blob)
                        entry = tarfile.TarInfo(base + "/" + name)
                        entry.size = len(data)
                        entry.mode = 0o755 if mode == "100755" else 0o644
                        entry.uid = entry.gid = entry.mtime = 0
                        entry.uname = entry.gname = ""
                        tar.addfile(entry, io.BytesIO(data))
        os.replace(temporary, archive)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    fd, temporary = tempfile.mkstemp(prefix=".checksums-", dir=output)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as destination:
            destination.write(f"{checksum}  {archive.name}\n")
        os.replace(temporary, checksum_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"ok": True, "archive": str(archive), "sha256": checksum, "files": len(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    try:
        print(json.dumps(package(Path(__file__).resolve().parents[1], args.output.absolute())))
    except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as exc:
        print(f"Release refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
