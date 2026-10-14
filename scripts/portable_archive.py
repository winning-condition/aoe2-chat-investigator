"""Create install-free archives, retaining Unix executable permissions."""
from pathlib import Path
import platform
import plistlib
import shutil
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = "AOE2-Chat-Investigator"
MAC_APP = "AOE2 Chat Investigator.app"


def archive_name(system=None, machine=None):
    system = system or platform.system()
    machine = machine or platform.machine()
    label = "macos" if system == "Darwin" else system.lower()
    extension = ".zip" if system == "Windows" else ".tar.gz"
    return f"{NAME}-{label}-{machine.lower()}{extension}"


def build_archive(root=ROOT, system=None, machine=None):
    root = Path(root)
    system = system or platform.system()
    binary = root / "dist" / (NAME + ".exe" if system == "Windows" else NAME)
    files = [(root / "LICENSE", "LICENSE"), (root / "mgz-fast/LICENSE", "Parser-LICENSE.txt")]
    if system == "Darwin":
        # Finder locates the executable through Info.plist. The console
        # bootloader keeps stdout available to the frozen CLI workers.
        contents = root / "dist" / MAC_APP / "Contents"
        executable = contents / "MacOS" / NAME
        executable.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, executable)
        executable.chmod(0o755)
        info = contents / "Info.plist"
        info.write_bytes(plistlib.dumps({
            "CFBundleName": "AOE2 Chat Investigator",
            "CFBundleDisplayName": "AOE2 Chat Investigator",
            "CFBundleIdentifier": "io.github.winning-condition.aoe2-chat-investigator",
            "CFBundleExecutable": NAME,
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "1",
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
        }))
        files += [(executable, f"{MAC_APP}/Contents/MacOS/{NAME}"),
                  (info, f"{MAC_APP}/Contents/Info.plist")]
        launch = f"Open {MAC_APP} in Finder. No Python or installer is needed."
    else:
        files.append((binary, binary.name))
        launch = (f"Double-click {binary.name}. No Python or installer is needed." if system == "Windows"
                  else f"Run ./{NAME} from this extracted folder. No Python or installer is needed.")
    readme = root / "dist" / "PORTABLE-README.txt"
    readme.write_text(
        "AOE2 Chat Investigator\n\n" + launch + "\n"
        "The app opens its local GUI in your default browser.\n"
        "Use Quit in the GUI to stop the app.\n\n"
        "Your watchlist, recordings and reports are saved outside this folder:\n"
        "  Windows: %LOCALAPPDATA%/AOE2 Chat Investigator\n"
        "  macOS: ~/Library/Application Support/AOE2 Chat Investigator\n"
        "  Linux: $XDG_DATA_HOME/AOE2 Chat Investigator\n"
        "         (normally ~/.local/share/AOE2 Chat Investigator)\n\n"
        "To use an existing data folder, pass --data-dir \"/path/to/folder\"\n"
        "to the executable. No reports or watchlist are included in this download.\n"
        "Add a player, then Fetch & extract; or Import replays and Extract local.\n"
        "Reports can be exported as Text and CSV.\n",
        encoding="utf-8")
    files.append((readme, "README.txt"))
    destination = root / "dist" / archive_name(system, machine)
    if system == "Windows":
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for source, target in files:
                archive.write(source, target)
    else:
        def release_metadata(info):
            info.mode = 0o755 if info.name in (NAME, f"{MAC_APP}/Contents/MacOS/{NAME}") else 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            return info
        with tarfile.open(destination, "w:gz") as archive:
            for source, target in files:
                archive.add(source, arcname=target, recursive=False, filter=release_metadata)
    return destination


if __name__ == "__main__":
    print(build_archive().name)
