import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import package_for_sharing as pfs


class TestPackageForSharing(unittest.TestCase):
    def test_input_filter_allows_only_templates_and_readmes(self):
        self.assertTrue(pfs._is_allowed("input/README.md"))
        self.assertTrue(pfs._is_allowed("input/templates/macro_settings.csv"))
        self.assertTrue(pfs._is_allowed("input/bank_statements/.gitkeep"))
        self.assertTrue(pfs._is_allowed("src/app.py"))
        for private in (
            "input/estratto.pdf",
            "input/notes.txt",
            "input/bank_statements/conto.csv",
            "input/wallet/export.ofx",
            "input/user_overrides.json",
        ):
            self.assertFalse(pfs._is_allowed(private), private)

    def test_zip_contains_no_personal_input(self):
        with TemporaryDirectory() as tmp:
            out = pfs.create_distribution_package(Path(tmp) / "x.zip")
            with zipfile.ZipFile(out) as zf:
                for name in zf.namelist():
                    self.assertTrue(pfs._is_allowed(name.split("/", 1)[1]), name)
                    self.assertFalse(name.endswith((".zip", ".env")), name)


if __name__ == "__main__":
    unittest.main()
