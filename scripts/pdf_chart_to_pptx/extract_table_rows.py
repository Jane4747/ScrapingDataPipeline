"""Build a figure draft from a numbered PDF table with count/percent column pairs."""

import argparse
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


CAPTION = re.compile(r"^\s*([图表])\s*([0-9]+(?:\.[0-9]+)*)(?=\s|$)")
COUNT = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
PERCENT = r"[0-9]+(?:\.[0-9]{1,2})?"
PAIR = rf"{COUNT}\s+{PERCENT}\s*[%％]"
ROW = re.compile(rf"^(?P<label>.+?)\s+(?P<pairs>{PAIR}(?:\s+{PAIR})*)$")
NUMBERS = re.compile(rf"({COUNT})\s+({PERCENT})\s*[%％]")
SAMPLE_N = re.compile(rf"[\[［]\s*N\s*=\s*({COUNT})\s*[\]］]", re.IGNORECASE)


def local_path(value):
    if "://" in value or value.startswith(("//", "\\\\")):
        raise argparse.ArgumentTypeError("请使用本地文件路径。")
    return Path(value)


def series_spec(value):
    name, sep, count = value.rpartition("=")
    if not sep or not name.strip() or not re.fullmatch(r"[0-9]+", count) or int(count) < 1:
        raise argparse.ArgumentTypeError("分组格式为 名称=正整数样本量。")
    return {"name": name.strip(), "n": int(count), "counts": [], "values": []}


def table_lines(reader, pages, table_id):
    """Limit rows to the given table and its continuation pages."""
    active = False
    for page in pages:
        for line in (reader.pages[page - 1].extract_text() or "").splitlines():
            caption = CAPTION.match(line)
            if caption:
                target = caption.groups() == ("表", table_id)
                if active and not target:
                    return
                active = target
            elif active:
                yield page, line.strip()
    if not active:
        raise ValueError(f"指定页未找到“表 {table_id}”的独立表题。请打开页图核对表号和可选文本。")


def extract(pdf, pages, table_id, series, expected_rows):
    reader = PdfReader(pdf)
    if (pages[0] < 1 or pages[-1] > len(reader.pages)
            or any(b != a + 1 for a, b in zip(pages, pages[1:]))):
        raise ValueError("页码必须是文件范围内、从 1 起算的连续升序 PDF 页码。")
    if expected_rows < 1 or len({group["name"] for group in series}) != len(series):
        raise ValueError("请填写正整数类别数及互不重复的分组名。")

    categories = []
    header_lines = []
    for page, line in table_lines(reader, pages, table_id):
        row = ROW.fullmatch(line)
        if not row:
            if not categories:
                header_lines.append(line)
            continue
        if not categories:
            header_ns = [int(n.replace(",", "")) for n in SAMPLE_N.findall(" ".join(header_lines))]
            if header_ns and header_ns != [group["n"] for group in series]:
                raise ValueError(f"表头样本量 {header_ns} 与 --series 的分母或顺序不符，请核对。")
        label = row["label"].strip()
        pairs = NUMBERS.findall(row["pairs"])
        if len(pairs) != len(series) or re.search(r"[0-9]\s*[%％]\s", label):
            raise ValueError(f"PDF 第 {page} 页列数或列顺序异常，请核对页图：{line}")
        if label in categories:
            raise ValueError(f"PDF 第 {page} 页类别重复，请核对页图：{label}")
        categories.append(label)
        for (count_text, percent_text), group in zip(pairs, series):
            count = int(count_text.replace(",", ""))
            percent = Decimal(percent_text)
            expected = (100 * Decimal(count) / group["n"]).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if count > group["n"] or percent != expected:
                raise ValueError(f"PDF 第 {page} 页 {label} / {group['name']}："
                                 f"{count}/{group['n']} 与标注 {percent}% 不符，请核对页图。")
            group["counts"].append(count)
            group["values"].append(float(percent / 100))
    if len(categories) != expected_rows:
        raise ValueError(f"预期 {expected_rows} 类，读取到 {len(categories)} 类。"
                         "请检查表题、续页和文本排列；纯图片请对照页图抄录。")
    return {"id": table_id, "pdfPages": pages, "categories": categories, "series": series}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=local_path, help="含中文编号配套表的本地 PDF")
    parser.add_argument("--pages", type=int, nargs="+", required=True, help="PDF 页码，从 1 开始")
    parser.add_argument("--id", required=True, help="图表编号，如 1.2.3")
    parser.add_argument("--series", type=series_spec, action="append", required=True,
                        help="按表列从左至右填写，每组一个 --series 名称=N")
    parser.add_argument("--rows", type=int, required=True, help="原图的类别数")
    parser.add_argument("--out", type=local_path, required=True, help="新建 JSON 草稿路径")
    args = parser.parse_args()
    try:
        result = extract(args.pdf, args.pages, args.id, args.series, args.rows)
        with args.out.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except (ValueError, OSError, PdfReadError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
