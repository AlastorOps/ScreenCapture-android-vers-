"""Source for Uninstall.exe -- a tiny stub installed alongside AndroidLink.exe
so the app's own install folder has a real, double-clickable uninstaller (item
11 of the "professional MSI installer" request), not just the Add/Remove
Programs entry.

Deliberately does NOT hardcode AndroidLink's MSI ProductCode: WiX's
<MajorUpgrade> support (androidlink.wxs) relies on the ProductCode changing
on every build (the standard, correct way to get real upgrade/downgrade
handling from Windows Installer), so a value baked in at build time would go
stale the moment a new version is installed over this one. Instead this
looks up the current installation's own "UninstallString" from the same
Windows Uninstall registry key that populates Settings > Apps > Installed
apps (matched by DisplayName), and simply re-runs it -- so the real work
(removing files/shortcuts/registry entries) is still done by Windows
Installer itself via the genuine MSI uninstall sequence, not reimplemented
here (reimplementing it would risk leaving something behind).
"""

import ctypes
import subprocess
import winreg

DISPLAY_NAME = "AndroidLink"

_UNINSTALL_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
)


def find_uninstall_string(display_name: str) -> str | None:
    for hive, path in _UNINSTALL_KEYS:
        try:
            uninstall_key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with uninstall_key:
            subkey_count = winreg.QueryInfoKey(uninstall_key)[0]
            for i in range(subkey_count):
                try:
                    subkey_name = winreg.EnumKey(uninstall_key, i)
                    with winreg.OpenKey(uninstall_key, subkey_name) as subkey:
                        name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                        if name == display_name:
                            uninstall_string, _ = winreg.QueryValueEx(subkey, "UninstallString")
                            return uninstall_string
                except OSError:
                    continue  # a subkey with no DisplayName/UninstallString -- not a real app entry
    return None


def main() -> None:
    uninstall_string = find_uninstall_string(DISPLAY_NAME)
    if uninstall_string is None:
        ctypes.windll.user32.MessageBoxW(
            0,
            "Could not find an AndroidLink installation record. It may already "
            "be uninstalled, or was installed by a different method.",
            "AndroidLink Uninstall",
            0x30,  # MB_ICONWARNING
        )
        return

    # UninstallString for an MSI-installed product is normally already
    # "MsiExec.exe /X{...GUID...}" -- shell=True since it's a single command
    # string from the registry, not a pre-split argument list.
    subprocess.run(uninstall_string, shell=True)


if __name__ == "__main__":
    main()
