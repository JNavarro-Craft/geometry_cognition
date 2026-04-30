from pathlib import Path
import rhino3dm as rg

OUT_DIR = Path("test_models/verification_cases")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def make_box(min_pt, max_pt):
    x0, y0, z0 = min_pt
    x1, y1, z1 = max_pt

    bbox = rg.BoundingBox(x0, y0, z0, x1, y1, z1)
    return bbox.ToBrep()


def add_box(doc, name, min_pt, max_pt, case_name):
    brep = make_box(min_pt, max_pt)

    attr = rg.ObjectAttributes()
    attr.Name = name
    attr.SetUserString("TestCase", case_name)
    attr.SetUserString("ElementName", name)
    attr.SetUserString("Source", "rhino3dm_test_model")

    doc.Objects.AddBrep(brep, attr)


def create_doc(case_name, boxes):
    doc = rg.File3dm()
    doc.Settings.ModelUnitSystem = rg.UnitSystem.Millimeters

    layer = rg.Layer()
    layer.Name = "Verification_Test"
    doc.Layers.Add(layer)

    for box in boxes:
        add_box(doc, **box, case_name=case_name)

    path = OUT_DIR / f"{case_name}.3dm"
    doc.Write(str(path), 7)
    print(f"created: {path}")


def main():
    create_doc(
        "case_A_touching_boxes",
        [
            {"name": "box_A", "min_pt": (0, 0, 0), "max_pt": (100, 100, 100)},
            {"name": "box_B", "min_pt": (100, 0, 0), "max_pt": (200, 100, 100)},
        ],
    )

    create_doc(
        "case_B_separated_boxes",
        [
            {"name": "box_A", "min_pt": (0, 0, 0), "max_pt": (100, 100, 100)},
            {"name": "box_B", "min_pt": (250, 0, 0), "max_pt": (350, 100, 100)},
        ],
    )

    create_doc(
        "case_C_intersecting_boxes",
        [
            {"name": "box_A", "min_pt": (0, 0, 0), "max_pt": (100, 100, 100)},
            {"name": "box_B", "min_pt": (50, 0, 0), "max_pt": (150, 100, 100)},
        ],
    )


if __name__ == "__main__":
    main()