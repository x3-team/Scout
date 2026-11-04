"""Windows-friendly CLI: python -m scout --scenario normal."""
import argparse
from pathlib import Path
import sys
from .mission import run_mission
from .models import load_scenario
from .report import write_html, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scout CPU-only synthetic inspection demo")
    parser.add_argument("--scenario", default="normal", help="bundled name or JSON file path")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("runs/report.json"))
    parser.add_argument("--html", type=Path, help="optional offline map and trajectory replay")
    args = parser.parse_args(argv)
    path = Path(args.scenario)
    if not path.is_file():
        if path.name != args.scenario or path.suffix:
            parser.error("scenario file does not exist")
        path = Path(__file__).parent / "scenarios" / f"{args.scenario}.json"
    outputs = [args.output.resolve()]
    if args.html:
        outputs.append(args.html.resolve())
    if len(set(outputs)) != len(outputs) or path.resolve() in outputs:
        parser.error("input, JSON output and HTML output must have different paths")
    try:
        scenario = load_scenario(path)
        report = run_mission(scenario, args.seed)
        write_json(report, args.output)
        if args.html:
            write_html(report, args.html)
    except (OSError, ValueError) as error:
        print(f"Scout error: {error}", file=sys.stderr)
        return 1
    print(f"{report['status']}: {report['reason']}; visited "
          f"{report['metrics']['visited_count']}/3; JSON: {args.output}")
    return 0 if report["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
