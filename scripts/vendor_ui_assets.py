"""Vendor the existing pinned UI dependencies, including their font files."""
from pathlib import Path
import argparse
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1] / 'static' / 'vendor'
STYLES = {
    'fontawesome': 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
    'bootstrap-icons': 'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css',
    'poppins': 'https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap',
}


def fetch(url):
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 Chrome/120.0.0.0 Safari/537.36'})
    with urlopen(request, timeout=30) as response:
        return response.read()


def vendor_flatpickr():
    folder = ROOT / 'flatpickr'
    folder.mkdir(parents=True, exist_ok=True)
    base = 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/'
    for filename, path in {
        'flatpickr.min.css': 'dist/flatpickr.min.css',
        'flatpickr.min.js': 'dist/flatpickr.min.js',
        'pt.js': 'dist/l10n/pt.js',
        'LICENSE.txt': 'LICENSE.md',
    }.items():
        (folder / filename).write_bytes(fetch(urljoin(base, path)))
    print('flatpickr: 4 files')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only-flatpickr', action='store_true')
    args = parser.parse_args()
    vendor_flatpickr()
    if args.only_flatpickr:
        return
    for name, url in STYLES.items():
        folder = ROOT / name
        folder.mkdir(parents=True, exist_ok=True)
        css = fetch(url).decode('utf-8')

        def download(match):
            remote = urljoin(url, match.group(1).strip('"\''))
            filename = Path(urlsplit(remote).path).name
            target = folder / filename
            if not target.exists():
                target.write_bytes(fetch(remote))
            return f'url("{filename}")'

        css = re.sub(r'url\(([^)]+)\)', download, css)
        (folder / 'style.css').write_text(css, encoding='utf-8')
        print(f'{name}: {len(list(folder.iterdir()))} files')
    folder = ROOT / 'inputmask'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'inputmask.min.js').write_bytes(fetch('https://cdn.jsdelivr.net/npm/inputmask@5.0.8/dist/inputmask.min.js'))
    licenses = {
        'fontawesome': 'https://raw.githubusercontent.com/FortAwesome/Font-Awesome/6.4.0/LICENSE.txt',
        'bootstrap-icons': 'https://raw.githubusercontent.com/twbs/icons/v1.10.5/LICENSE',
        'poppins': 'https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/OFL.txt',
        'inputmask': 'https://raw.githubusercontent.com/RobinHerbots/Inputmask/5.0.8/LICENSE.txt',
    }
    for name, url in licenses.items():
        (ROOT / name / 'LICENSE.txt').write_bytes(fetch(url))


if __name__ == '__main__':
    main()
