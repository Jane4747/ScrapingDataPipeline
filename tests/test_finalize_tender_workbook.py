import json
from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from finalize_tender_workbook import finalize, S, R, P


class WorkbookLinksTests(unittest.TestCase):
    def fixture(self, root):
        book = root / 'input.xlsx'
        sheet = f'<worksheet xmlns="{S}" xmlns:r="{R}"><sheetData><row r="1"><c r="A1"><v>12.5</v></c></row></sheetData><hyperlinks><hyperlink ref="A1" r:id="old"/><hyperlink ref="B1" r:id="unrelated"/></hyperlinks><pageMargins/></worksheet>'
        rel = f'<Relationships xmlns="{P}"><Relationship Id="old" Type="{R}/hyperlink" Target="https://example.org/old" TargetMode="External"/><Relationship Id="unrelated" Type="{R}/hyperlink" Target="https://example.org/keep" TargetMode="External"/></Relationships>'
        with ZipFile(book, 'w') as z:
            z.writestr('xl/worksheets/sheet1.xml', sheet)
            z.writestr('xl/worksheets/_rels/sheet1.xml.rels', rel)
            z.writestr('unrelated.txt', 'preserved')
        links = root / 'links.json'
        links.write_text(json.dumps([{'sheet':1, 'cell':'A1', 'url':'https://example.org/new'}]), encoding='utf-8')
        return book, links

    def test_repeat_keeps_other_links_and_original_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); book, links = self.fixture(root); original = book.read_bytes()
            first, second = root / 'first.xlsx', root / 'second.xlsx'
            finalize(book, links, first); finalize(first, links, second)
            self.assertEqual(book.read_bytes(), original)
            with ZipFile(second) as z:
                sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
                self.assertEqual(len(sheet.findall(f'.//{{{S}}}hyperlink')), 2)
                self.assertEqual(sheet.find(f'.//{{{S}}}v').text, '12.5')
                rel = ET.fromstring(z.read('xl/worksheets/_rels/sheet1.xml.rels'))
                self.assertEqual({r.get('Target') for r in rel}, {'https://example.org/new','https://example.org/keep'})
                self.assertEqual(z.read('unrelated.txt'), b'preserved')

    def test_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); book, links = self.fixture(root)
            with self.assertRaises(ValueError): finalize(book, links, book)

    def test_rejects_non_web_link_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); book, links = self.fixture(root); output = root / 'out.xlsx'
            links.write_text(json.dumps([{'sheet':1,'cell':'A1','url':'file:///private'}]),encoding='utf-8')
            with self.assertRaises(ValueError): finalize(book, links, output)
            self.assertFalse(output.exists())

    def test_conflicting_cell_urls_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); book,links=self.fixture(root)
            links.write_text(json.dumps([{'sheet':1,'cell':'A1','url':url} for url in ['https://example.org/a','https://example.org/b']]),encoding='utf-8')
            with self.assertRaises(ValueError): finalize(book,links,root/'out.xlsx')


if __name__ == '__main__':
    unittest.main()
