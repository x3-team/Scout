"""Compute pixels on synthetic fixtures; never claim real photo validation."""
from pathlib import Path
import subprocess
import sys


def main():
    root = Path('runs/vision')
    def run(*arguments, expected=0):
        r = subprocess.run([sys.executable, '-m', 'scout.vision', *map(str, arguments)], timeout=45)
        if r.returncode != expected:
            raise SystemExit('unexpected vision demo exit: ' + str(r.returncode))
    run('board', '--output-dir', root / 'board')
    run('fixtures', '--output-dir', root / 'fixtures')
    for name in ('unchanged', 'changed', 'perspective', 'brighter', 'removed',
                 'missing-marker', 'occluded', 'blurred', 'dark'):
        expected = 2 if name in ('missing-marker', 'occluded', 'blurred', 'dark') else 0
        run('inspect', '--reference', root / 'fixtures/reference.png',
            '--current', root / ('fixtures/' + name + '.png'), '--input-kind', 'synthetic',
            '--output-dir', root / ('reports/' + name), expected=expected)
    print('Nine image demonstrations computed. Inputs are synthetic; photo accuracy is unmeasured.')


if __name__ == '__main__':
    main()
