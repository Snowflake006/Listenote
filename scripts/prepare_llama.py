"""Developer-only fetch of pinned official CPU engine; end users never download this."""
from pathlib import Path
import sys
import zipfile
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Listenote' / 'app'))
from resources import download_file

TAG = 'b12098'
DIGEST = '8d142d409515ce7a0f873654170ef0071d945acd1918fd774d374840917bf211'
if __name__ == '__main__':
    archive = ROOT / '.test-data' / f'llama-{TAG}-cpu.zip'
    download_file(f'https://github.com/ggml-org/llama.cpp/releases/download/{TAG}/llama-{TAG}-bin-win-cpu-x64.zip',
                  archive, lambda n, text: None, lambda: False, DIGEST, 24708083)
    target = ROOT / 'Listenote' / 'tools' / 'llama'
    target.mkdir(parents=True, exist_ok=True)
    names = set()
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            name = Path(entry.filename).name
            if name == 'llama-server.exe' or name.endswith('.dll'):
                if name in names:
                    raise RuntimeError('Unexpected duplicate engine file')
                names.add(name)
                (target / name).write_bytes(package.read(entry))
    response = requests.get(f'https://raw.githubusercontent.com/ggml-org/llama.cpp/{TAG}/LICENSE', timeout=30)
    response.raise_for_status()
    (target / 'LICENSE.txt').write_text(response.text, 'utf8')
    print('Engine verified and staged:', len(names), 'files', flush=True)
