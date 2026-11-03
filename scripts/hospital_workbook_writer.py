"""Write per-hospital website probe results back into the roster workbook.

Default behaviour is dry-run: the command reports every planned cell change and
writes nothing. Only `--apply` touches the workbook, and it always takes a backup
copy first so a wrong batch can be undone.

Only rows with an explicit probe match are written. Rows that are absent from the
probe records keep whatever they already contain, so a partial batch never blanks
review work that was done earlier by hand.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

LIST_HEADERS = [
    '原行号', '医院名称', '等级别', '举办主体',
    '医院本级官网首页', '本级官网有无采购栏目', '探针执行状态', '证据摘要',
]


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def column_index(letter):
    letter = letter.strip().upper()
    result = 0
    for char in letter:
        if not char.isalpha():
            raise ValueError(f'Column must be letters only: {letter}')
        result = result * 26 + (ord(char) - 64)
    return result


def index_rows(sheet, head_row, name_col, owner_col=None, level_col=None):
    mapping = {}
    for row in sheet.iter_rows(min_row=head_row + 1, max_row=sheet.max_row):
        name = row[name_col - 1].value
        if not isinstance(name, str) or not name.strip():
            continue
        key = name.strip()
        if key in mapping:
            continue
        mapping[key] = {
            'row': row[0].row,
            'level': row[level_col - 1].value if level_col else None,
            'owner': row[owner_col - 1].value if owner_col else None,
        }
    return mapping


def status_text(record, config):
    labels = config.get('status_labels', {})
    status = record.get('channel_status') or 'unknown'
    if status == 'found':
        candidate = record.get('top_candidate') or {}
        return labels.get('found', 'found') + '（' + (candidate.get('anchor') or candidate.get('url') or '') + '）'
    if status == 'not_found':
        return labels.get('not_found', 'not_found') + '；已访问本级官网'
    reason = '；'.join(sorted({(item.get('status') or '') for item in record.get('evidence', []) if item.get('status')}))
    return labels.get('unknown', 'unknown') + (f'（{reason}）' if reason else '')


def build_changes(records, mapping, args, config):
    changes = []
    unmatched = []
    for record in records:
        entry = mapping.get(record.get('hospital_name', '').strip())
        if not entry:
            unmatched.append(record.get('hospital_name'))
            continue
        row = entry['row']
        if not record.get('homepage_url'):
            changes.append({'row': row, 'column': args.status_col,
                            'value': '本级官网未定位；' + status_text(record, config), 'reason': 'no_homepage'})
            continue
        if args.homepage_col:
            changes.append({'row': row, 'column': args.homepage_col,
                            'value': record['homepage_url'], 'reason': 'homepage'})
        if args.status_col:
            changes.append({'row': row, 'column': args.status_col,
                            'value': status_text(record, config), 'reason': 'status'})
        candidate = record.get('top_candidate')
        if candidate and args.update_channel and args.channel_col:
            changes.append({'row': row, 'column': args.channel_col,
                            'value': candidate['url'], 'reason': 'column'})
    return changes, unmatched


def list_rows(records, mapping):
    rows = []
    for record in records:
        if record.get('channel_status') == 'found':
            continue
        entry = mapping.get(record.get('hospital_name', '').strip()) or {}
        rows.append([
            entry.get('row'), record.get('hospital_name'),
            record.get('level'), record.get('owner'),
            record.get('homepage_url') or '未定位',
            '有' if record.get('channel_status') == 'found' else '无',
            record.get('channel_status') or 'unknown',
            '；'.join(f"{item.get('target_url')}={item.get('status')}" for item in record.get('evidence', [])),
        ])
    return rows


def apply_workbook(args, changes, list_sheet_rows):
    source = Path(args.workbook)
    target = Path(args.output) if args.output else source
    if args.apply and not args.no_backup:
        backup = source.with_suffix(source.suffix + '.bak')
        shutil.copyfile(source, backup)
    workbook = load_workbook(source)
    sheet = workbook[args.sheet]
    for change in changes:
        sheet.cell(row=change['row'], column=column_index(change['column'])).value = change['value']
    if args.list_sheet:
        if args.list_sheet in workbook.sheetnames:
            del workbook[args.list_sheet]
        listing = workbook.create_sheet(args.list_sheet)
        listing.append(LIST_HEADERS)
        for row in list_sheet_rows:
            listing.append(row)
        fill = PatternFill('solid', fgColor='1F4E79')
        for cell in listing[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = fill
        for column in range(1, len(LIST_HEADERS) + 1):
            listing.column_dimensions[get_column_letter(column)].width = 22 if column < 7 else 60
            for cell in listing[get_column_letter(column)]:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
        listing.freeze_panes = 'A2'
    workbook.save(target)
    return str(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--sheet', required=True)
    parser.add_argument('--records', required=True, help='probe_records.json from hospital_site_probe.py')
    parser.add_argument('--config', default=str(Path(__file__).resolve().parents[1] / 'configs' / 'hospital_site_probe.json'))
    parser.add_argument('--head-row', type=int, default=4)
    parser.add_argument('--name-col', default='C')
    parser.add_argument('--level-col', default='D')
    parser.add_argument('--owner-col', default='H')
    parser.add_argument('--homepage-col', default='T')
    parser.add_argument('--status-col', default='U')
    parser.add_argument('--channel-col', default='S')
    parser.add_argument('--update-channel', action='store_true', help='Overwrite S column when a column is located')
    parser.add_argument('--list-sheet', default='06-未找到待核查清单')
    parser.add_argument('--apply', action='store_true', help='Actually write; without it only the plan is printed')
    parser.add_argument('--output')
    parser.add_argument('--no-backup', action='store_true')
    args = parser.parse_args(argv)
    try:
        config = read_json(args.config)
        records = read_json(args.records)
        workbook = load_workbook(args.workbook)
        if args.sheet not in workbook.sheetnames:
            raise ValueError(f'Missing sheet: {args.sheet}')
        mapping = index_rows(workbook[args.sheet], args.head_row, column_index(args.name_col),
                             column_index(args.owner_col), column_index(args.level_col))
        changes, unmatched = build_changes(records, mapping, args, config)
        rows = list_rows(records, mapping)
        payload = {'status': 'planned', 'change_count': len(changes), 'list_row_count': len(rows),
                   'unmatched_hospitals': unmatched, 'changes': changes[:50]}
        if args.apply:
            target = apply_workbook(args, changes, rows)
            payload.update({'status': 'completed', 'written_to': target})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
