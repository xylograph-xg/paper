"""Offline build, isolated install and default ZIP extraction release gate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent

def verify(root):
    entries = json.loads((root / 'interface.json').read_text(encoding='utf-8'))['entries']
    for entry in entries:
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('unsafe path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('hash mismatch: ' + entry['path'])
    return entries

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    entries = verify(ROOT)
    with tempfile.TemporaryDirectory() as scratch:
        temp = Path(scratch)
        source = temp / 'source'
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('dist', 'build', '*.egg-info', '__pycache__', '.DS_Store'))
        subprocess.run([sys.executable, '-m', 'pip', 'wheel', str(source), '--no-deps', '--no-build-isolation', '-w', str(temp / 'wheel')], check=True, stdout=subprocess.PIPE)
        wheel = next((temp / 'wheel').glob('*.whl'))
        with zipfile.ZipFile(wheel) as archive:
            for entry in entries:
                raw = archive.read('reports/' + entry['path'])
                if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                    raise ValueError('wheel hash mismatch')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--target', str(temp / 'installed'), str(wheel)], check=True, stdout=subprocess.PIPE)
        code = "import reports.api as a; entries=a.list_reports(); [a.read_report(e['path']) for e in entries]; print('installed_verified',len(entries))"
        env = dict(os.environ, PYTHONPATH=str(temp / 'installed'), PYTHONNOUSERSITE='1')
        subprocess.run([sys.executable, '-S', '-c', code], cwd=temp, env=env, check=True)
        delivery = temp / 'reports.zip'
        with zipfile.ZipFile(delivery, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob('*')):
                if path.is_file() and not any(p in {'build', '__pycache__'} or p.endswith('.egg-info') for p in path.relative_to(source).parts):
                    archive.write(path, 'reports/' + path.relative_to(source).as_posix())
        with zipfile.ZipFile(delivery) as archive:
            if any(not i.filename.isascii() and not i.flag_bits & 0x800 for i in archive.infolist()):
                raise ValueError('ZIP UTF8 flag missing')
            archive.extractall(temp / 'extracted')
        verify(temp / 'extracted' / 'reports')
        result = {'manifest': len(entries), 'wheel_verified': len(entries), 'installed_verified': len(entries), 'zip_verified': len(entries)}
        if not args.check:
            args.output.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wheel, args.output / wheel.name)
            shutil.copy2(delivery, args.output / delivery.name)
            (args.output / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))

if __name__ == '__main__':
    main()
