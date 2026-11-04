"""Source receipts from clean Git checkouts or verified immutable snapshots."""
import hashlib
import json
from pathlib import Path
import subprocess

SKILLFORGE_REF = 'fa57ef94ce64539f19f8fdd75210a5d25ebb2da8'


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def source_record(root, *, snapshot_pin=None, expected_commit=None):
    root = Path(root).resolve()
    if snapshot_pin:
        receipt = json.loads(Path(snapshot_pin).read_text(encoding='utf-8'))
        commit = receipt['commit']
        files = receipt['files']
        paths = [item['path'] for item in files]
        if len(paths) != len(set(paths)):
            raise ValueError('duplicate source path')
        for item in files:
            path = root/item['path']
            if not path.resolve().is_relative_to(root):
                raise ValueError('source path outside snapshot')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != item['sha256']:
                raise ValueError('source snapshot changed: '+item['path'])
            if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != item['git_blob_sha']:
                raise ValueError('source Git blob mismatch: '+item['path'])
    else:
        def git(*args):
            return subprocess.check_output(['git','-C',str(root),*args])
        if git('status','--porcelain','--untracked-files=normal').strip():
            raise ValueError('source checkout must be clean before a measured run')
        commit = git('rev-parse','HEAD').decode().strip()
        paths = git('ls-files','-z').decode('utf-8').rstrip('\0').split('\0')
    if expected_commit is not None and commit != expected_commit:
        raise ValueError('source commit differs from the reviewed worker pin')
    records = [{'path':p,'sha256':hashlib.sha256((root/p).read_bytes()).hexdigest()}
               for p in sorted(paths,key=lambda p:p.encode('utf-8'))]
    return {'commit':commit,'source_sha256':hashlib.sha256(canonical(records)).hexdigest()}
