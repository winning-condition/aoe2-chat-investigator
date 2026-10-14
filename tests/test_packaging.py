"""Release layout checks. Native execution is covered by portable_smoke.py."""
from pathlib import Path
import plistlib
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.portable_archive import build_archive, MAC_APP, NAME


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="aoe2 package layout ")
        self.root = Path(self.temp.name)
        (self.root / "dist").mkdir()
        (self.root / "mgz-fast").mkdir()
        (self.root / "LICENSE").write_text("Application license")
        (self.root / "mgz-fast/LICENSE").write_text("Parser license")
        # These checks validate the archive structure, not a foreign executable.
        (self.root / "dist" / NAME).write_bytes(b"layout-test-only")
        (self.root / "dist" / (NAME + ".exe")).write_bytes(b"layout-test-only")
        (self.root / "watchlist.json").write_text('[{"name":"PrivatePlayer"}]')
        (self.root / "dist/unrelated.txt").write_text("Must not ship")

    def tearDown(self):
        self.temp.cleanup()

    def test_windows_archive_includes_executable_instructions_and_licenses_only(self):
        artifact = build_archive(self.root, "Windows", "AMD64")
        with zipfile.ZipFile(artifact) as archive:
            self.assertEqual(set(archive.namelist()), {NAME + ".exe", "README.txt", "LICENSE", "Parser-LICENSE.txt"})
            self.assertIn(b"Double-click", archive.read("README.txt"))
            self.assertEqual(archive.read(NAME + ".exe"), b"layout-test-only")

    def test_linux_archive_retains_executable_permission_and_no_user_data(self):
        artifact = build_archive(self.root, "Linux", "x86_64")
        with tarfile.open(artifact) as archive:
            self.assertEqual(set(archive.getnames()), {NAME, "README.txt", "LICENSE", "Parser-LICENSE.txt"})
            self.assertEqual(archive.getmember(NAME).mode, 0o755)
            self.assertIn(b"Run ./AOE2-Chat-Investigator", archive.extractfile("README.txt").read())

    def test_mac_app_metadata_resolves_an_executable_inside_the_archive(self):
        for machine in ("arm64", "x86_64"):
            artifact = build_archive(self.root, "Darwin", machine)
            self.assertIn(f"macos-{machine}", artifact.name)
            with tarfile.open(artifact) as archive:
                info = plistlib.loads(archive.extractfile(f"{MAC_APP}/Contents/Info.plist").read())
                self.assertEqual(info["CFBundlePackageType"], "APPL")
                executable = f"{MAC_APP}/Contents/MacOS/{info['CFBundleExecutable']}"
                self.assertEqual(archive.getmember(executable).mode, 0o755)
                self.assertEqual(archive.extractfile(executable).read(), b"layout-test-only")
                self.assertEqual(set(archive.getnames()), {executable, f"{MAC_APP}/Contents/Info.plist", "README.txt", "LICENSE", "Parser-LICENSE.txt"})
                self.assertIn(b"in Finder", archive.extractfile("README.txt").read())


if __name__ == "__main__":
    unittest.main()
