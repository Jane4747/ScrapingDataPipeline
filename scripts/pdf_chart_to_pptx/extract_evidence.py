"""Extract selected PDF pages as text and page images; this does not infer chart values."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from pypdf import PdfReader
from validate_data import validate


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--config', help='Validated chart configuration')
    source.add_argument('--pdf', type=Path, help='Source PDF for review before preparing chart data')
    parser.add_argument('--pages', nargs='+', type=int, help='One-based PDF pages, with --pdf')
    parser.add_argument('--output', required=True)
    parser.add_argument('--poppler', default='pdftoppm')
    args = parser.parse_args()
    if args.pdf is not None:
        if not args.pages:
            parser.error('--pdf requires --pages')
        pdf_path = args.pdf
        pages = sorted(set(args.pages))
    else:
        if args.pages:
            parser.error('--pages is used only with --pdf')
        config_path = Path(args.config).resolve()
        config, _ = validate(config_path)
        pdf_path = config_path.parent / config['source']['path']
        pages = sorted({p for figure in config['figures'] for p in figure.get('pdfPages', [])})
    if not pages or min(pages) < 1:
        parser.error('Specify at least one positive, one-based PDF page')
    pdf_path = pdf_path.resolve(strict=True)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    reader = PdfReader(pdf_path)
    records = []
    for number in pages:
        if number > len(reader.pages):
            raise ValueError(f'PDF page {number} exceeds page count {len(reader.pages)}')
        stem = output / f'pdf-{number:03}'
        content = reader.pages[number - 1].extract_text() or ''
        stem.with_suffix('.txt').write_text(content, encoding='utf-8')
        result = subprocess.run([args.poppler, '-f', str(number), '-l', str(number), '-singlefile',
                                 '-scale-to', '1900', '-png', str(pdf_path), str(stem)],
                                capture_output=True, text=True, errors='replace', check=True)
        records.append({'pdfPage': number, 'textCharacters': len(content),
                        'image': stem.with_suffix('.png').name, 'text': stem.with_suffix('.txt').name,
                        'renderWarnings': result.stderr.strip()})
    with pdf_path.open('rb') as source_stream:
        source_hash = hashlib.file_digest(source_stream, 'sha256').hexdigest()
    metadata = {'source': str(pdf_path), 'sha256': source_hash,
                'extractedAtUtc': datetime.now(timezone.utc).isoformat(), 'pageCount': len(reader.pages),
                'pages': records, 'scope': 'Text extraction and rendering only. Chart values require visual review.'}
    (output / 'source.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'completed', 'pages': pages}, ensure_ascii=True))


if __name__ == '__main__':
    main()
