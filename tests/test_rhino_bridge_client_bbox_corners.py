from types import SimpleNamespace

from gc_mcp.rhino_bridge_client import tools as rhino_tools


class _FakePoint:
    def __init__(self, x: float, y: float, z: float) -> None:
        self.X = x
        self.Y = y
        self.Z = z


class _FakeBoundingBox:
    def __init__(self, mn: tuple[float, float, float], mx: tuple[float, float, float]) -> None:
        self.Min = _FakePoint(*mn)
        self.Max = _FakePoint(*mx)
        self.IsValid = True


class _FakeGeom:
    def __init__(self, bbox: _FakeBoundingBox | None) -> None:
        self._bbox = bbox

    def GetBoundingBox(self):
        return self._bbox


def test_geometry_bounding_box_includes_bbox_corners_and_points():
    geom = _FakeGeom(_FakeBoundingBox((0.0, 1.0, 2.0), (3.0, 4.0, 5.0)))
    summary = rhino_tools._geometry_bounding_box(geom)
    assert summary is not None
    assert "bbox" in summary
    corners = summary.get("bbox_corners")
    assert isinstance(corners, list)
    assert len(corners) == 8
    assert all(isinstance(p, list) and len(p) == 3 for p in corners)
    assert summary.get("sample_points")


def test_rhino_object_adds_warning_when_bbox_corners_not_available(monkeypatch):
    class _GeomNoBbox:
        pass

    class _Attrs:
        ObjectId = "obj-1"
        Name = "n"
        LayerIndex = -1
        UserStringCount = 0
        Transform = None

        def GetGroupList(self):
            return []

    fake_obj = SimpleNamespace(Attributes=_Attrs(), Geometry=_GeomNoBbox())
    fake_file = SimpleNamespace(Layers=[])
    fake_rhino = SimpleNamespace(InstanceReference=type("InstanceReference", (), {}))

    monkeypatch.setattr(rhino_tools, "_geometry_bounding_box", lambda _g: None)
    out = rhino_tools._to_dict_from_rhino_object(fake_file, fake_obj, {}, fake_rhino)
    assert "bbox_corners_not_available" in out.get("extraction_warnings", [])
