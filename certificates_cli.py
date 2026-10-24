import os
import sys
from pathlib import Path


def main():
    if getattr(sys, "frozen", False):
        runtime = Path(sys.executable).parent / "runtime/powershell"
        if not (runtime / "pwsh.exe").is_file():
            raise RuntimeError("The offline PowerShell runtime is unavailable.")
        os.environ["PATH"] = str(runtime) + os.pathsep + os.environ.get("PATH", "")
    from tools.certificates import main as certificate_main

    if any(value == "--activate-profile" or value.startswith("--activate-profile=") for value in sys.argv[1:]):
        raise ValueError("Use KioskMaintenance.exe provision-https for installed certificate activation.")
    return certificate_main()


if __name__ == "__main__":
    raise SystemExit(main())
