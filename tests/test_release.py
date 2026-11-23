"""Offline source-release regressions; Git writes stay in temporary fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = "omarchy-remote-buttons-0.1.0"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="buttons-release-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.put("scripts/make-release.py", (ROOT / "scripts/make-release.py").read_text()
                 if (ROOT / "scripts/make-release.py").exists() else "raise SystemExit('release helper not implemented')\n")
        for name in ("Panel.qml", "Model.js", "remote_buttons.py", "README.md", "LICENSE", "agent/SKILL.md"):
            self.put(name, "reviewed fixture\n")
        self.put("manifest.json", json.dumps({"id": "leo.remote-buttons", "version": "0.1.0"}))
        self.git("add", ".")
        self.output = Path(self.temp.name) / "output"

    def git(self, *args, input=None):
        return subprocess.check_output(["git", *args], cwd=self.repo, input=input, stderr=subprocess.PIPE)

    def put(self, name, data):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)

    def release(self):
        return subprocess.run([sys.executable, str(self.repo / "scripts/make-release.py"), "--output", str(self.output)],
                              cwd=self.repo, capture_output=True, text=True, timeout=20)

    def contents(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = Path(json.loads(result.stdout)["archive"])
        with tarfile.open(archive) as tar:
            contents = {}
            for entry in tar.getmembers():
                stream = tar.extractfile(entry)
                self.assertIsNotNone(stream)
                assert stream is not None
                contents[entry.name.removeprefix(BASE + "/")] = stream.read()
            return contents

    def test_deterministic_button_only_archive_and_checksum(self):
        self.put("private-recording.wav", "untracked private data")
        first = self.release()
        contents = self.contents(first)
        self.assertEqual(contents["README.md"], b"reviewed fixture\n")
        self.assertEqual(len(contents), 8)
        archive = self.output / (BASE + ".tar.gz")
        before = archive.read_bytes()
        self.assertEqual(self.release().returncode, 0)
        self.assertEqual(before, archive.read_bytes())
        self.assertEqual((self.output / "SHA256SUMS").read_text(), hashlib.sha256(before).hexdigest() + "  " + archive.name + "\n")
        with tarfile.open(archive) as tar:
            names = tar.getnames()
            self.assertEqual(names, sorted(names))
            self.assertTrue(all(e.isfile() and e.uid == e.gid == e.mtime == 0 and e.uname == e.gname == "" and e.mode == 0o644 for e in tar.getmembers()))
        self.assertEqual(before[4:8], b"\0\0\0\0")

    def test_allowlist_excludes_private_contract_and_refuses_unexpected_roots(self):
        self.put("ARCHITECTURE.md", "private implementation contract")
        self.git("add", "ARCHITECTURE.md")
        self.assertNotIn("ARCHITECTURE.md", self.contents(self.release()))
        for name in ("personal.txt", "patches/old.patch", "third_party/LICENSE"):
            with self.subTest(name=name):
                self.put(name, "not distributable")
                self.git("add", name)
                result = self.release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unexpected", result.stderr.lower())
                self.git("rm", "--cached", name)

    def test_plain_plugin_instructions_do_not_require_a_project_agent_file(self):
        contents = self.contents(self.release())
        self.assertIn("README.md", contents)
        self.assertIn("agent/SKILL.md", contents)
        self.assertNotIn("AGENTS.md", contents)

    def test_required_indexed_files_are_mandatory(self):
        for name in ("manifest.json", "Panel.qml", "Model.js", "remote_buttons.py", "README.md", "LICENSE", "agent/SKILL.md", "scripts/make-release.py"):
            with self.subTest(name=name):
                self.git("update-index", "--force-remove", name)
                result = self.release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("required", result.stderr.lower())
                self.git("add", name)

    def test_nonregular_index_entries_are_refused(self):
        blob = self.git("rev-parse", ":README.md").decode().strip()
        for mode, name in (("120000", "docs/link.md"), ("160000", "docs/submodule")):
            with self.subTest(mode=mode):
                self.git("update-index", "--add", "--cacheinfo", mode + "," + blob + "," + name)
                result = self.release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("nonregular", result.stderr.lower())
                self.git("update-index", "--force-remove", name)

    def test_unsafe_index_names_are_refused(self):
        for name in ("docs/bad\nname.md", "docs/space name.md", "docs/naïve.md"):
            with self.subTest(name=name):
                self.put(name, "text")
                self.git("add", name)
                result = self.release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unsafe", result.stderr.lower())
                self.git("rm", "--cached", name)

    def test_private_generated_and_audio_paths_are_refused(self):
        for name in ("docs/.env", "docs/.env.local", "tests/__pycache__/bad.pyc", "docs/config.json",
                     "tests/recording.wav", "scripts/build-bridge.py", "tests/audio.py", "docs/credentials.txt",
                     "docs/id_rsa", "docs/private.key", "docs/config.local.json", "docs/output.log", "docs/out.tar.gz"):
            with self.subTest(name=name):
                self.put(name, "private or unsupported")
                self.git("add", name)
                result = self.release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("private/generated/audio", result.stderr.lower())
                self.git("rm", "--cached", name)

    def test_dirty_tracked_sources_are_refused(self):
        self.put("README.md", "not staged for review")
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unstaged", result.stderr.lower())

    def test_indexed_size_cap_cannot_be_hidden_by_worktree_flags(self):
        self.put("README.md", "x" * (4 * 1024 * 1024 + 1))
        self.git("add", "README.md")
        self.git("update-index", "--skip-worktree", "README.md")
        self.put("README.md", "small decoy")
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("oversized", result.stderr.lower())

    def test_aggregate_and_entry_caps_are_enforced(self):
        helper = self.repo / "scripts/make-release.py"
        helper.write_text(helper.read_text().replace("MAX_FILES = 512", "MAX_FILES = 9").replace("MAX_TOTAL_BYTES = 16 * 1024 * 1024", "MAX_TOTAL_BYTES = 20000"))
        self.git("add", "scripts/make-release.py")
        self.put("docs/large.md", "x" * 20000)
        self.git("add", "docs/large.md")
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("total", result.stderr.lower())
        self.git("rm", "--cached", "docs/large.md")
        for i in range(2):
            self.put("docs/entry-" + str(i) + ".md", "small")
        self.git("add", "docs/entry-0.md", "docs/entry-1.md")
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("count", result.stderr.lower())

    def test_manifest_identity_and_version_are_validated(self):
        for value in ({"id":"other.plugin","version":"0.1.0"}, {"id":"leo.remote-buttons","version":"../../escape"},
                      {"id":"leo.remote-buttons","version":None}, {"id":"leo.remote-buttons","version":"01.1.0"}, []):
            with self.subTest(value=value):
                self.put("manifest.json", json.dumps(value))
                self.git("add", "manifest.json")
                result = self.release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("manifest", result.stderr.lower())

    def test_binary_home_paths_and_obvious_credentials_are_refused(self):
        for data in (b"binary\0payload", b"\xffnot utf8", ("/ho" + "me/alice/private/config").encode(),
                     ("/ro" + "ot/.secret").encode(), ("-----BEGIN " + "PRIVATE KEY-----").encode(),
                     ("gh" + "p_" + "A" * 30).encode()):
            with self.subTest(data=data[:12]):
                (self.repo / "README.md").write_bytes(data)
                self.git("add", "README.md")
                result = self.release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("content", result.stderr.lower())

    def test_symlinked_outputs_are_refused_before_any_publication(self):
        self.output.mkdir()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        victim = outside / "keep"
        victim.write_text("untouched")
        for name in (BASE + ".tar.gz", "SHA256SUMS"):
            with self.subTest(name=name):
                link = self.output / name
                link.symlink_to(victim)
                result = self.release()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("symlink", result.stderr.lower())
                self.assertEqual(victim.read_text(), "untouched")
                self.assertFalse((self.output / BASE).exists())
                link.unlink()
        shutil.rmtree(self.output)
        self.output.symlink_to(outside, target_is_directory=True)
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr.lower())
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ["keep"])

    def test_index_flags_never_substitute_unreviewed_bytes_or_version(self):
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag):
                self.git("update-index", flag, "README.md", "manifest.json")
                self.put("README.md", "UNREVIEWED_SENTINEL")
                self.put("manifest.json", json.dumps({"version":"99.99.99"}))
                contents = self.contents(self.release())
                self.assertEqual(contents["README.md"], b"reviewed fixture\n")
                self.assertEqual(json.loads(contents["manifest.json"])["version"], "0.1.0")

    def test_replace_refs_cannot_substitute_blob_data(self):
        indexed = self.git("rev-parse", ":README.md").decode().strip()
        replacement = self.git("hash-object", "-w", "--stdin", input=b"UNREVIEWED_REPLACEMENT").decode().strip()
        self.git("replace", indexed, replacement)
        self.git("update-index", "--assume-unchanged", "README.md")
        self.assertEqual(self.contents(self.release())["README.md"], b"reviewed fixture\n")

    def test_support_directories_and_index_executable_modes_are_preserved(self):
        for name in ("tests/fixtures/hyprctl", "i18n/en.json", ".github/workflows/ci.yml", "docs/example.md", "agent/reference.md"):
            self.put(name, "reviewed support file")
            self.git("add", name)
        (self.repo / "tests/fixtures/hyprctl").chmod(0o755)
        self.git("update-index", "--chmod=+x", "tests/fixtures/hyprctl")
        result = self.release()
        contents = self.contents(result)
        self.assertIn("tests/fixtures/hyprctl", contents)
        with tarfile.open(json.loads(result.stdout)["archive"]) as tar:
            self.assertEqual(tar.getmember(BASE + "/tests/fixtures/hyprctl").mode, 0o755)

    def test_unmerged_index_stages_are_refused(self):
        blob = self.git("rev-parse", ":README.md").decode().strip()
        self.git("update-index", "--force-remove", "README.md")
        row = ("100644 " + blob + " 1\tREADME.md\n").encode()
        self.git("update-index", "--index-info", input=row)
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("conflicted", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
