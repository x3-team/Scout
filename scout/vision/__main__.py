"""Optional image CLI, entirely separate from the virtual robot runner."""
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description='Scout 02 CPU image inspection')
    commands = parser.add_subparsers(dest='command', required=True)
    board = commands.add_parser('board', help='write printable board.svg and board.png')
    board.add_argument('--output-dir', type=Path, required=True)
    fixtures = commands.add_parser('fixtures', help='write explicitly synthetic test images')
    fixtures.add_argument('--output-dir', type=Path, required=True)
    inspect = commands.add_parser('inspect', help='compare two image files')
    inspect.add_argument('--reference', type=Path, required=True)
    inspect.add_argument('--current', type=Path, required=True)
    inspect.add_argument('--input-kind', choices=('photograph', 'synthetic'), required=True)
    inspect.add_argument('--output-dir', type=Path, required=True)
    inspect.add_argument('--config', type=Path)
    evaluate = commands.add_parser('evaluate', help='measure a labelled held-out dataset')
    evaluate.add_argument('--manifest', type=Path, required=True)
    evaluate.add_argument('--output', type=Path, required=True)
    evaluate.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    try:
        from .engine import VisionConfig, analyze_pair
        config = VisionConfig(**json.loads(args.config.read_text(encoding='utf-8'))) if getattr(args, 'config', None) else VisionConfig()
        if args.command == 'board':
            from .board import write_board
            write_board(args.output_dir)
        elif args.command == 'fixtures':
            from .fixtures import write_fixtures
            write_fixtures(args.output_dir)
        elif args.command == 'inspect':
            output = args.output_dir.resolve()
            inputs = [args.reference, args.current] + ([args.config] if args.config else [])
            if any(p.resolve().is_relative_to(output) for p in inputs):
                raise ValueError('input images must be outside the output directory')
            from .reporting import write_analysis
            result, pictures = analyze_pair(args.reference, args.current,
                                            input_kind=args.input_kind, config=config)
            write_analysis(output, result, pictures)
            print(result['result'] + ': ' + result['reason'])
            return 2 if result['result'] == 'INCONCLUSIVE' else 0
        else:
            from .evaluate import evaluate_manifest
            if args.output.resolve() == args.manifest.resolve():
                raise ValueError('output cannot overwrite dataset manifest')
            manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
            if not isinstance(manifest, dict) or not isinstance(manifest.get('pairs'), list):
                raise ValueError('invalid dataset manifest')
            if any(not isinstance(pair, dict) or not {'reference', 'current'} <= set(pair)
                   or not isinstance(pair['reference'], str) or not isinstance(pair['current'], str)
                   for pair in manifest['pairs']):
                raise ValueError('invalid dataset image paths')
            protected = [(args.manifest.parent / pair[key]).resolve()
                         for pair in manifest.get('pairs', []) for key in ('reference', 'current')]
            if args.config:
                protected.append(args.config.resolve())
            if args.output.resolve() in protected:
                raise ValueError('output cannot overwrite an input image or configuration')
            result = evaluate_manifest(args.manifest, config)
            from scout.report import atomic_write
            atomic_write(args.output, json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
            print('Evaluation written; lab acceptance: ' + str(result['acceptance_passed']))
    except ImportError:
        print('Vision dependencies missing. Run: python -m pip install -r requirements-vision.txt', file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError) as error:
        print('Scout vision error: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
