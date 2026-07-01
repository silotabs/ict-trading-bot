from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import paper_api


class PhaseP12PackagingStage6ClosureTests(unittest.TestCase):
    def test_pyproject_declares_backend_project_metadata(self):
        text = (REPO_ROOT / "pyproject.toml").read_text()
        self.assertRegex(text, r'(?m)^name = "trading-paper-stack"$')
        self.assertRegex(text, r'(?m)^version = "0\.1\.0"$')
        self.assertRegex(text, r'(?m)^requires-python = ">=3\.11"$')

    def test_paper_api_package_boundary_exists(self):
        self.assertEqual(paper_api.__version__, "0.1.0")
        self.assertIn("__version__", paper_api.__all__)

    def test_readme_indexes_p12_and_mentions_packaging_metadata(self):
        text = (REPO_ROOT / "paper_api" / "README.md").read_text()
        self.assertIn("pyproject.toml", text)
        self.assertIn("dossier/29_phase_p12_packaging_stage6_closure.md", text)
        self.assertIn("hold_for_more_shadow_evidence", text)

    def test_p12_doc_keeps_stage_truth_conservative(self):
        text = (REPO_ROOT / "dossier" / "29_phase_p12_packaging_stage6_closure.md").read_text()
        self.assertIn("Stage 6: Concept Proof / Acceptance Testing", text)
        self.assertIn("Stage 7: Promotion or Rejection Decision", text)
        self.assertIn("hold_for_more_shadow_evidence", text)
        self.assertIn("candidate for controlled live planning: `no`", text)

    def test_stage_roadmap_still_marks_stage_6_current(self):
        text = (REPO_ROOT / "dossier" / "13_stage_roadmap.md").read_text()
        self.assertIn("`Stage 6: Concept Proof / Acceptance Testing`", text)
        self.assertIn("Status:\n\n- `current`", text)
        self.assertIn("Status:\n\n- `not started`", text)


if __name__ == "__main__":
    unittest.main()
