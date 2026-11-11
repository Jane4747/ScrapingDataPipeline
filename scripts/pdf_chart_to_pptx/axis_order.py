"""Set native horizontal bar categories top-to-bottom without reversing data.

Usage: python axis_order.py input.pptx output.pptx
The input deck stays unchanged. Only the requested category/value-axis settings
of horizontal bar charts are adjusted; series and workbook values are untouched.
"""
import sys
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as ET


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python axis_order.py input.pptx output.pptx")
    source, target = map(Path, sys.argv[1:])
    if source.resolve() == target.resolve():
        raise ValueError("Input and output must be different paths.")
    if target.exists():
        raise FileExistsError(f"Output already exists: {target}")
    ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
    changed = 0
    with ZipFile(source) as original, ZipFile(target, "x") as result:
        for item in original.infolist():
            content = original.read(item.filename)
            if "/charts/chart" in item.filename and item.filename.endswith(".xml"):
                root = ET.fromstring(content)
                direction = root.find(".//c:barChart/c:barDir", ns)
                if direction is not None and direction.get("val") == "bar":
                    for axis in root.findall(".//c:catAx", ns):
                        scaling = axis.find("c:scaling", ns)
                        if scaling is None:
                            raise ValueError(f"Missing category scaling: {item.filename}")
                        orientation = scaling.find("c:orientation", ns)
                        if orientation is None:
                            orientation = ET.SubElement(scaling, "{" + ns["c"] + "}orientation")
                        orientation.set("val", "maxMin")
                    for axis in root.findall(".//c:valAx", ns):
                        crosses = axis.find("c:crosses", ns)
                        crosses_at = axis.find("c:crossesAt", ns)
                        if crosses_at is not None:
                            axis.remove(crosses_at)
                        if crosses is None:
                            cross_axis = axis.find("c:crossAx", ns)
                            if cross_axis is None:
                                raise ValueError(f"Missing cross-axis reference: {item.filename}")
                            crosses = ET.Element("{" + ns["c"] + "}crosses")
                            axis.insert(list(axis).index(cross_axis) + 1, crosses)
                        crosses.set("val", "max")
                    content = ET.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
                    changed += 1
            result.writestr(item, content)
    if changed == 0:
        raise ValueError("No native horizontal bar chart was found.")
    print(f"Adjusted category order in {changed} native chart(s).")


if __name__ == "__main__":
    main()
