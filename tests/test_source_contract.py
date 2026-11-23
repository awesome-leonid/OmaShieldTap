"""Portable source must not embed a developer's personal home directory."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PortableSourceTests(unittest.TestCase):
    def test_distributed_sources_do_not_embed_personal_home_paths(self):
        files = [p for p in ROOT.iterdir() if p.is_file() and p.name not in {'ARCHITECTURE.md'}]
        for folder in ('tests', 'scripts', 'agent', 'docs', 'i18n', '.github'):
            base = ROOT / folder
            if base.exists():
                files.extend(p for p in base.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
        for path in files:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(re.search(rb'/h[o]me/[A-Za-z0-9_.-]+', path.read_bytes()),
                                  'Personal home path embedded in distributed source')


if __name__ == '__main__':
    unittest.main()
