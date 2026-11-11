"""Check percentage-chart data without changing the supplied values."""
import argparse
import json
import math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


def validate(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(config, dict):
        raise ValueError('Config must be an object')
    if config.get('schema') != 'pdf-percent-charts.v1':
        raise ValueError('schema must be pdf-percent-charts.v1')
    for key in ('title', 'source', 'figures'):
        if not config.get(key):
            raise ValueError(f'Missing {key}')
    source = config['source']
    if not isinstance(source, dict):
        raise ValueError('source must be an object')
    for key in ('path', 'title', 'organization'):
        if not isinstance(source.get(key), str) or not source[key].strip():
            raise ValueError(f'Missing source.{key}')
    if not config['figures'] or not isinstance(config['figures'], list):
        raise ValueError('figures must be a nonempty list')
    ids, summaries = set(), []
    for figure in config['figures']:
        if not isinstance(figure, dict):
            raise ValueError('Each figure must be an object')
        fid = figure.get('id')
        if not isinstance(fid, str) or not fid.strip() or fid in ids:
            raise ValueError('Figure ids must be nonempty and unique')
        ids.add(fid)
        if 'multiResponse' in figure and not isinstance(figure['multiResponse'], bool):
            raise ValueError(f'{fid}: multiResponse must be a boolean')
        if 'countUnit' in figure and (not isinstance(figure['countUnit'], str) or not figure['countUnit'].strip()):
            raise ValueError(f'{fid}: countUnit must be a nonempty string')
        categories = figure.get('categories', [])
        if not isinstance(categories, list) or not categories or not all(isinstance(v, str) and v.strip() for v in categories):
            raise ValueError(f'{fid}: missing category labels')
        if len(set(categories)) != len(categories):
            raise ValueError(f'{fid}: duplicate category labels')
        if not isinstance(figure.get('series'), list) or not figure['series']:
            raise ValueError(f'{fid}: missing series')
        if not isinstance(figure.get('pdfPages', []), list):
            raise ValueError(f'{fid}: pdfPages must be a list')
        for p in figure.get('pdfPages', []):
            if type(p) is not int or p < 1:
                raise ValueError(f'{fid}: PDF pages must be positive 1-based integers')
        names = set()
        for series in figure['series']:
            if not isinstance(series, dict):
                raise ValueError(f'{fid}: each series must be an object')
            name = series.get('name')
            if not isinstance(name, str) or not name.strip() or name in names:
                raise ValueError(f'{fid}: missing or duplicate series name')
            names.add(name)
            values = series.get('values', [])
            if not isinstance(values, list) or len(values) != len(categories):
                raise ValueError(f'{fid}/{name}: category/value length mismatch')
            if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
                raise ValueError(f'{fid}/{name}: percentage fractions must be finite and between 0 and 1')
            # Displayed 0.01 percentage-point precision corresponds to 0.0001 as a fraction.
            if any(abs(v - round(v, 4)) > 1e-12 for v in values):
                raise ValueError(f'{fid}/{name}: values exceed the supported 0.01 percentage-point precision')
            n, counts = series.get('n'), series.get('counts')
            if n is not None and (type(n) is not int or n <= 0):
                raise ValueError(f'{fid}/{name}: N must be a positive integer when supplied')
            if counts is not None:
                if not isinstance(counts, list) or len(counts) != len(categories) or any(v is not None and (type(v) is not int or v < 0) for v in counts):
                    raise ValueError(f'{fid}/{name}: invalid counts')
                if n is not None:
                    for count, value in zip(counts, values):
                        if count is None:
                            continue
                        if count > n:
                            raise ValueError(f'{fid}/{name}: count exceeds N')
                        expected = (Decimal(count) / Decimal(n)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
                        if abs(float(expected) - value) > 1e-12:
                            raise ValueError(f'{fid}/{name}: percentage does not match count/N')
            summaries.append({'figure': fid, 'series': name, 'N': n,
                              'points': len(values), 'percentageSum': None if figure.get('multiResponse') else round(sum(values) * 100, 2),
                              'countSum': sum(counts) if counts is not None and None not in counts and not figure.get('multiResponse') else None})
    return config, summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    args = parser.parse_args()
    _, summaries = validate(args.config)
    print(json.dumps({'status': 'validated', 'series': summaries}, ensure_ascii=True))
