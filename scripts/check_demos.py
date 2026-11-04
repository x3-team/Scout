"""Run from repository root; nonzero stop/fault demo exit codes are expected."""
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    for name, status, exit_code in (("normal", "COMPLETED", 0),
                                     ("deviations", "COMPLETED", 0),
                                     ("blocked", "BLOCKED", 2),
                                     ("sensor-failure", "FAULT", 2)):
        destination = Path("runs") / name
        process = subprocess.run([sys.executable, "-m", "scout", "--scenario", name,
                                  "--seed", "1", "--output", str(destination.with_suffix(".json")),
                                  "--html", str(destination.with_suffix(".html"))], timeout=20)
        if process.returncode != exit_code:
            raise SystemExit(f"{name}: expected exit {exit_code}, got {process.returncode}")
        report = json.loads(destination.with_suffix(".json").read_text(encoding="utf-8"))
        if (report["status"] != status or not report["stopped"]
                or report["metrics"]["collision_guard_activations"] != 0):
            raise SystemExit(f"{name}: unexpected result")
        script = re.findall(r"<script>(.*?)</script>",
                            destination.with_suffix(".html").read_text(encoding="utf-8"), re.S)[0]
        destination.with_suffix(".js").write_text(script, encoding="utf-8")
    print("All four demonstration outcomes match their expected results.")


if __name__ == "__main__":
    main()
