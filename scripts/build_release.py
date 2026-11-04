"""Build the portable Windows archive and the upgrade package from local files."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.1.0'
PORTABLE = ROOT / 'Listenote'


def archive(path, files):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for file in files:
            output.write(file, file.relative_to(ROOT).as_posix())
    print(f'{path.name}: {path.stat().st_size} bytes', flush=True)


if __name__ == '__main__':
    full = ROOT / f'Listenote-Windows-x64-v{VERSION}.zip'
    update = ROOT / f'Listenote-AI-Update-v{VERSION}.zip'
    files = sorted(p for p in PORTABLE.rglob('*') if p.is_file() and
                   '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo', '.log'))
    archive(full, files)
    changed = ['app/main.py', 'app/startup.py', 'app/ai_summary.py', 'app/ai_ui.py', '使用说明.txt', 'preview.png']
    archive(update, [PORTABLE / name for name in changed])
    checksums = []
    for path in (full, update):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        checksums.append(f'{digest}  {path.name}\n')
    (ROOT / 'SHA256.txt').write_text(''.join(checksums), encoding='utf8')
    print('SHA256.txt updated', flush=True)
