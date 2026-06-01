using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Text;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;
using Rhino.Geometry.Intersect;

namespace RhinoPrefabGeometryPlugin.Services;

public class NeutralGeometryService
{
    [DataContract]
    public sealed class RelationVerificationRequest
    {
        [DataMember(Name = "relation_id")]
        public string RelationId { get; set; } = string.Empty;

        [DataMember(Name = "subject_id")]
        public string SubjectId { get; set; } = string.Empty;

        [DataMember(Name = "object_id")]
        public string ObjectId { get; set; } = string.Empty;

        [DataMember(Name = "check")]
        public string Check { get; set; } = string.Empty;
    }

    [DataContract]
    public sealed class VerificationTolerance
    {
        [DataMember(Name = "linear_tolerance")]
        public double LinearTolerance { get; set; } = 0.05;

        [DataMember(Name = "angular_tolerance")]
        public double AngularTolerance { get; set; } = 2.0;

        [DataMember(Name = "unit_system")]
        public string UnitSystem { get; set; } = "model_unit";
    }

    [DataContract]
    public sealed class LiveObjectsQueryEnvelope
    {
        [DataMember(Name = "filters")]
        public LiveQueryFilters? Filters { get; set; }

        [DataMember(Name = "fields")]
        public List<string>? Fields { get; set; }

        [DataMember(Name = "limit")]
        public int? Limit { get; set; }

        [DataMember(Name = "cursor")]
        public int? Cursor { get; set; }

        // Not part of the wire contract: filled by ParseLiveObjectsQuery with any
        // keys found inside "filters" that are not recognized, so the response can
        // warn instead of silently ignoring a mistyped filter (the DataContract
        // serializer drops unknown keys, which otherwise looks like "no filter").
        public List<string> UnknownFilterKeys { get; set; } = new List<string>();
    }

    private static readonly HashSet<string> KnownFilterKeys = new HashSet<string>(
        new[] { "layers", "types", "name_contains", "has_user_text", "user_text_key", "user_text_value", "bbox_intersects" },
        StringComparer.Ordinal);

    private static List<string> DetectUnknownFilterKeys(string body)
    {
        // Lax scan: find the "filters" object in the raw body and list its top-level
        // keys, then subtract the known ones. Regex-based to avoid adding a JSON dep;
        // best-effort (only flags clearly-unknown keys, never blocks the request).
        var unknown = new List<string>();
        if (string.IsNullOrWhiteSpace(body))
        {
            return unknown;
        }
        var m = System.Text.RegularExpressions.Regex.Match(
            body, "\"filters\"\\s*:\\s*\\{", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        if (!m.Success)
        {
            return unknown;
        }
        // Walk braces from the opening { to find the matching close, so nested
        // objects (e.g. bbox_intersects) do not end the scan prematurely.
        int start = m.Index + m.Length - 1;
        int depth = 0;
        int end = -1;
        for (int i = start; i < body.Length; i++)
        {
            if (body[i] == '{') depth++;
            else if (body[i] == '}') { depth--; if (depth == 0) { end = i; break; } }
        }
        if (end < 0)
        {
            return unknown;
        }
        var filtersBlock = body.Substring(start, end - start + 1);
        // Top-level keys only: a key is "..." followed by ':' at brace depth 1.
        int d = 0;
        foreach (System.Text.RegularExpressions.Match km in System.Text.RegularExpressions.Regex.Matches(
            filtersBlock, "[{}]|\"([^\"]+)\"\\s*:"))
        {
            if (km.Value == "{") { d++; continue; }
            if (km.Value == "}") { d--; continue; }
            if (d == 1)
            {
                var key = km.Groups[1].Value;
                if (!KnownFilterKeys.Contains(key) && !unknown.Contains(key))
                {
                    unknown.Add(key);
                }
            }
        }
        return unknown;
    }

    [DataContract]
    public sealed class LiveQueryFilters
    {
        [DataMember(Name = "layers")]
        public List<string>? Layers { get; set; }

        [DataMember(Name = "types")]
        public List<string>? Types { get; set; }

        [DataMember(Name = "name_contains")]
        public string? NameContains { get; set; }

        [DataMember(Name = "has_user_text")]
        public bool? HasUserText { get; set; }

        [DataMember(Name = "user_text_key")]
        public string? UserTextKey { get; set; }

        [DataMember(Name = "user_text_value")]
        public string? UserTextValue { get; set; }

        [DataMember(Name = "bbox_intersects")]
        public LiveBboxFilter? BboxIntersects { get; set; }
    }

    [DataContract]
    public sealed class LiveBboxFilter
    {
        [DataMember(Name = "min")]
        public List<double>? Min { get; set; }

        [DataMember(Name = "max")]
        public List<double>? Max { get; set; }
    }

    public static LiveObjectsQueryEnvelope ParseLiveObjectsQuery(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            return new LiveObjectsQueryEnvelope();
        }
        try
        {
            using var ms = new MemoryStream(Encoding.UTF8.GetBytes(body));
            var serializer = new DataContractJsonSerializer(typeof(LiveObjectsQueryEnvelope));
            var parsed = serializer.ReadObject(ms) as LiveObjectsQueryEnvelope ?? new LiveObjectsQueryEnvelope();
            parsed.UnknownFilterKeys = DetectUnknownFilterKeys(body);
            return parsed;
        }
        catch (SerializationException ex)
        {
            throw new InvalidOperationException($"Invalid JSON payload: {ex.Message}");
        }
    }

    public Dictionary<string, object> LiveSceneSummary(RhinoDoc doc, int sampleLimit)
    {
        sampleLimit = Math.Max(0, Math.Min(100, sampleLimit));
        var typeCounts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var global = BoundingBox.Unset;
        var total = 0;
        foreach (var obj in doc.Objects)
        {
            total++;
            var geom = obj.Geometry;
            var typeName = geom?.ObjectType.ToString() ?? "Unknown";
            if (!typeCounts.TryGetValue(typeName, out var c))
            {
                c = 0;
            }
            typeCounts[typeName] = c + 1;
            var bbox = GetValidBbox(geom);
            if (bbox.IsValid)
            {
                global = global.IsValid ? BoundingBox.Union(global, bbox) : bbox;
            }
        }

        var sample = new List<object>();
        var taken = 0;
        foreach (var obj in doc.Objects)
        {
            if (taken >= sampleLimit)
            {
                break;
            }
            sample.Add(ExtractObjectLiveLight(doc, obj, "none"));
            taken++;
        }

        return new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["api"] = "v1_live",
            ["object_count"] = total,
            ["global_bbox"] = BboxToSummaryDict(global),
            ["type_counts"] = typeCounts
                .OrderBy(kv => kv.Key, StringComparer.OrdinalIgnoreCase)
                .ToDictionary(kv => kv.Key, kv => (object)kv.Value),
            ["sample_objects"] = sample,
            ["sample_limit"] = sampleLimit
        };
    }

    public Dictionary<string, object> LiveQueryObjects(RhinoDoc doc, LiveObjectsQueryEnvelope request)
    {
        var limit = Math.Max(1, Math.Min(500, request.Limit ?? 100));
        var cursor = Math.Max(0, request.Cursor ?? 0);
        var filters = request.Filters;
        var filterBbox = TryParseFilterBbox(filters?.BboxIntersects);
        var layerSet = NormalizeFilterList(filters?.Layers);
        var typeSet = NormalizeFilterList(filters?.Types);
        var nameNeedle = (filters?.NameContains ?? string.Empty).Trim();
        var hasUserText = filters?.HasUserText;
        var utKey = (filters?.UserTextKey ?? string.Empty).Trim();
        var utVal = filters?.UserTextValue;

        var matched = new List<RhinoObject>();
        foreach (var obj in doc.Objects)
        {
            if (!PassesLiveFilters(doc, obj, layerSet, typeSet, nameNeedle, hasUserText, utKey, utVal, filterBbox))
            {
                continue;
            }
            matched.Add(obj);
        }

        var totalMatched = matched.Count;
        var page = matched.Skip(cursor).Take(limit).ToList();
        int? nextCursor = cursor + page.Count < totalMatched ? cursor + page.Count : null;

        var fieldSet = NormalizeFieldSet(request.Fields);
        var rows = new List<object>();
        foreach (var obj in page)
        {
            rows.Add(BuildQueryObjectRow(doc, obj, fieldSet));
        }

        var result = new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["api"] = "v1_live",
            ["matched_count"] = totalMatched,
            ["returned_count"] = rows.Count,
            ["limit"] = limit,
            ["cursor"] = cursor,
            ["objects"] = rows
        };
        if (nextCursor.HasValue)
        {
            result["next_cursor"] = nextCursor.Value;
        }
        if (request.UnknownFilterKeys is { Count: > 0 })
        {
            // Surface mistyped/unsupported filter keys instead of silently ignoring
            // them. A caller seeing matched_count == total can check this to learn
            // the filter never applied (e.g. "where"/"layer" instead of "layers").
            result["filter_warnings"] = new Dictionary<string, object>
            {
                ["unknown_filter_keys"] = request.UnknownFilterKeys.Cast<object>().ToList(),
                ["known_filter_keys"] = KnownFilterKeys.OrderBy(k => k, StringComparer.Ordinal).Cast<object>().ToList(),
                ["note"] = "These filter keys are not recognized and were ignored; matched_count reflects the remaining (possibly empty) filter."
            };
        }
        return result;
    }

    public Dictionary<string, object> LiveGetObject(
        RhinoDoc doc,
        string objectIdToken,
        string detailLevel,
        string userTextMode)
    {
        var obj = TryFindObject(doc, objectIdToken);
        if (obj is null)
        {
            throw new KeyNotFoundException($"Object not found: {objectIdToken}");
        }

        detailLevel = (detailLevel ?? "basic").Trim().ToLowerInvariant();
        userTextMode = (userTextMode ?? "keys").Trim().ToLowerInvariant();

        if (detailLevel == "full")
        {
            var full = ExtractObject(doc, obj);
            ApplyUserTextModeToMap(full, obj.Attributes, userTextMode);
            full["api"] = "v1_live";
            return full;
        }

        return BuildLiveObjectBasic(doc, obj, userTextMode);
    }

    // ---- Detailed per-element geometry access (vertices / edges / faces) ----
    //
    // These expose the raw topology+geometry of a solid that the aggregate fields
    // (face_count, face_areas[i], face_normals[i], edge_count) cannot: the actual
    // vertex coordinates, each edge's endpoints/length, and each face's boundary
    // (which edges bound it). Universal across Brep / Extrusion / Mesh; an
    // unsupported type raises an honest error rather than returning empty.

    private const double PlanarToleranceMm = 1e-3;

    // Resolve an object's geometry to a Brep for per-element access. Mesh is handled
    // separately (different topology API), so this returns null for Mesh on purpose.
    private static Brep? GeometryAsBrepForElements(GeometryBase? geometry)
    {
        if (geometry is Brep b) return b;
        if (geometry is Extrusion ext) { try { return ext.ToBrep(true); } catch { return null; } }
        if (geometry is Surface s) { try { return s.ToBrep(); } catch { return null; } }
        return null;
    }

    public Dictionary<string, object> LiveGetVertices(RhinoDoc doc, string objectIdToken)
    {
        var (obj, geometry) = ResolveGeometryOrThrow(doc, objectIdToken);
        var vertices = new List<object>();

        var brep = GeometryAsBrepForElements(geometry);
        if (brep is not null)
        {
            int i = 0;
            foreach (var v in brep.Vertices)
            {
                var p = v.Location;
                vertices.Add(new Dictionary<string, object> { ["index"] = i++, ["coord"] = new List<double> { p.X, p.Y, p.Z } });
            }
        }
        else if (geometry is Mesh mesh)
        {
            var tv = mesh.TopologyVertices;
            for (int i = 0; i < tv.Count; i++)
            {
                var p = tv[i];
                vertices.Add(new Dictionary<string, object> { ["index"] = i, ["coord"] = new List<double> { p.X, p.Y, p.Z } });
            }
        }
        else
        {
            throw new InvalidOperationException($"get_vertices: unsupported geometry type '{geometry?.ObjectType.ToString() ?? "Unknown"}' (Brep/Extrusion/Mesh only).");
        }

        return ElementResult(obj, geometry, "vertices", vertices);
    }

    public Dictionary<string, object> LiveGetEdges(RhinoDoc doc, string objectIdToken)
    {
        var (obj, geometry) = ResolveGeometryOrThrow(doc, objectIdToken);
        var edges = new List<object>();

        var brep = GeometryAsBrepForElements(geometry);
        if (brep is not null)
        {
            for (int i = 0; i < brep.Edges.Count; i++)
            {
                edges.Add(BrepEdgeToDict(i, brep.Edges[i]));
            }
        }
        else if (geometry is Mesh mesh)
        {
            var te = mesh.TopologyEdges;
            for (int i = 0; i < te.Count; i++)
            {
                var line = te.EdgeLine(i);
                edges.Add(new Dictionary<string, object>
                {
                    ["index"] = i,
                    ["start"] = new List<double> { line.From.X, line.From.Y, line.From.Z },
                    ["end"] = new List<double> { line.To.X, line.To.Y, line.To.Z },
                    ["length"] = line.Length,
                    ["is_curved"] = false,   // mesh edges are straight segments
                    ["samples"] = null!,
                });
            }
        }
        else
        {
            throw new InvalidOperationException($"get_edges: unsupported geometry type '{geometry?.ObjectType.ToString() ?? "Unknown"}' (Brep/Extrusion/Mesh only).");
        }

        return ElementResult(obj, geometry, "edges", edges);
    }

    public Dictionary<string, object> LiveGetFaces(RhinoDoc doc, string objectIdToken)
    {
        var (obj, geometry) = ResolveGeometryOrThrow(doc, objectIdToken);
        var faces = new List<object>();

        var brep = GeometryAsBrepForElements(geometry);
        if (brep is not null)
        {
            for (int i = 0; i < brep.Faces.Count; i++)
            {
                faces.Add(BrepFaceToDict(i, brep.Faces[i]));
            }
        }
        else if (geometry is Mesh mesh)
        {
            mesh.Normals.ComputeNormals();
            var te = mesh.TopologyEdges;
            for (int i = 0; i < mesh.Faces.Count; i++)
            {
                faces.Add(MeshFaceToDict(i, mesh, te));
            }
        }
        else
        {
            throw new InvalidOperationException($"get_faces: unsupported geometry type '{geometry?.ObjectType.ToString() ?? "Unknown"}' (Brep/Extrusion/Mesh only).");
        }

        return ElementResult(obj, geometry, "faces", faces);
    }

    private (RhinoObject Obj, GeometryBase Geometry) ResolveGeometryOrThrow(RhinoDoc doc, string objectIdToken)
    {
        var obj = TryFindObject(doc, objectIdToken);
        if (obj is null)
        {
            throw new KeyNotFoundException($"Object not found: {objectIdToken}");
        }
        var geometry = obj.Geometry;
        if (geometry is null)
        {
            throw new InvalidOperationException($"Object has no geometry: {objectIdToken}");
        }
        return (obj, geometry);
    }

    private static Dictionary<string, object> ElementResult(
        RhinoObject obj, GeometryBase geometry, string key, List<object> items)
    {
        return new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["api"] = "v1_live",
            ["object_id"] = obj.Id.ToString(),
            ["type"] = geometry.ObjectType.ToString(),
            ["count"] = items.Count,
            [key] = items,
        };
    }

    private static Dictionary<string, object> BrepEdgeToDict(int index, BrepEdge edge)
    {
        var start = edge.PointAtStart;
        var end = edge.PointAtEnd;
        double length;
        try { length = edge.GetLength(); } catch { length = start.DistanceTo(end); }
        // is_curved: not a straight line within tolerance. IsLinear is the direct test.
        bool isCurved;
        try { isCurved = !edge.IsLinear(PlanarToleranceMm); } catch { isCurved = false; }

        var dict = new Dictionary<string, object>
        {
            ["index"] = index,
            ["start"] = new List<double> { start.X, start.Y, start.Z },
            ["end"] = new List<double> { end.X, end.Y, end.Z },
            ["length"] = length,
            ["is_curved"] = isCurved,
            ["samples"] = null!,
        };
        if (isCurved)
        {
            dict["samples"] = SampleCurve(edge, 12).Select(p => (object)new List<double> { p.X, p.Y, p.Z }).ToList();
        }
        return dict;
    }

    private static Dictionary<string, object> BrepFaceToDict(int index, BrepFace face)
    {
        // Normal at the middle of the face's parameter domain.
        var u = face.Domain(0).Mid;
        var v = face.Domain(1).Mid;
        var n = face.NormalAt(u, v);
        if (!n.IsTiny(1e-9)) n.Unitize();

        double area = 0.0;
        var centroid = Point3d.Origin;
        var amp = AreaMassProperties.Compute(face);
        if (amp is not null)
        {
            area = amp.Area;
            centroid = amp.Centroid;
        }

        bool isPlanar;
        try { isPlanar = face.IsPlanar(PlanarToleranceMm); } catch { isPlanar = false; }

        // Topology: which edges bound this face. Walk the loops -> trims -> edge index.
        // -1 trims (singular/seam without an edge) are skipped. Distinct + sorted.
        var edgeIdx = new SortedSet<int>();
        double perimeter = 0.0;
        var seen = new HashSet<int>();
        foreach (var loop in face.Loops)
        {
            foreach (var trim in loop.Trims)
            {
                var ei = trim.Edge?.EdgeIndex ?? -1;
                if (ei >= 0)
                {
                    edgeIdx.Add(ei);
                    if (seen.Add(ei))
                    {
                        try { perimeter += trim.Edge!.GetLength(); } catch { }
                    }
                }
            }
        }

        return new Dictionary<string, object>
        {
            ["index"] = index,
            ["normal"] = new List<double> { n.X, n.Y, n.Z },
            ["area"] = area,
            ["centroid"] = new List<double> { centroid.X, centroid.Y, centroid.Z },
            ["perimeter"] = perimeter,
            ["is_planar"] = isPlanar,
            ["edge_indices"] = edgeIdx.Cast<object>().ToList(),
        };
    }

    private static Dictionary<string, object> MeshFaceToDict(int index, Mesh mesh, Rhino.Geometry.Collections.MeshTopologyEdgeList te)
    {
        var mf = mesh.Faces[index];
        var corners = mf.IsQuad
            ? new[] { mesh.Vertices[mf.A], mesh.Vertices[mf.B], mesh.Vertices[mf.C], mesh.Vertices[mf.D] }
            : new[] { mesh.Vertices[mf.A], mesh.Vertices[mf.B], mesh.Vertices[mf.C] };

        // Face normal (computed) and centroid.
        var fn = mesh.FaceNormals.Count > index ? mesh.FaceNormals[index] : new Vector3f(0, 0, 1);
        var normal = new Vector3d(fn.X, fn.Y, fn.Z);
        if (!normal.IsTiny(1e-9)) normal.Unitize();

        double cx = 0, cy = 0, cz = 0;
        foreach (var c in corners) { cx += c.X; cy += c.Y; cz += c.Z; }
        int nc = corners.Length;
        var centroid = new Point3d(cx / nc, cy / nc, cz / nc);

        // Area: triangle, or quad as two triangles.
        double TriArea(Point3f a, Point3f b, Point3f c)
            => 0.5 * Vector3d.CrossProduct(
                   new Vector3d(b.X - a.X, b.Y - a.Y, b.Z - a.Z),
                   new Vector3d(c.X - a.X, c.Y - a.Y, c.Z - a.Z)).Length;
        double area = mf.IsQuad
            ? TriArea(corners[0], corners[1], corners[2]) + TriArea(corners[0], corners[2], corners[3])
            : TriArea(corners[0], corners[1], corners[2]);

        double perimeter = 0.0;
        for (int i = 0; i < nc; i++)
        {
            var a = corners[i];
            var b = corners[(i + 1) % nc];
            perimeter += a.DistanceTo(b);
        }

        var edgeIdx = new SortedSet<int>();
        var fe = te.GetEdgesForFace(index);
        if (fe is not null)
        {
            foreach (var e in fe) edgeIdx.Add(e);
        }

        return new Dictionary<string, object>
        {
            ["index"] = index,
            ["normal"] = new List<double> { normal.X, normal.Y, normal.Z },
            ["area"] = area,
            ["centroid"] = new List<double> { centroid.X, centroid.Y, centroid.Z },
            ["perimeter"] = perimeter,
            ["is_planar"] = true,   // mesh faces (tri/quad) are treated as planar facets
            ["edge_indices"] = edgeIdx.Cast<object>().ToList(),
        };
    }

    public Dictionary<string, object> LiveListDefinitions(RhinoDoc doc)
    {
        // List block (instance) definitions with instance counts and a bbox derived
        // from the definition's own objects. Agnostic: names are opaque data.
        var defs = new List<object>();
        var table = doc.InstanceDefinitions;
        if (table is not null)
        {
            foreach (var idef in table)
            {
                if (idef is null || idef.IsDeleted)
                {
                    continue;
                }
                int instanceCount;
                try
                {
                    instanceCount = idef.GetReferences(0)?.Length ?? 0;
                }
                catch
                {
                    instanceCount = 0;
                }

                var defBbox = BoundingBox.Unset;
                var memberIds = idef.GetObjectIds() ?? Array.Empty<Guid>();
                foreach (var mid in memberIds)
                {
                    var mobj = doc.Objects.FindId(mid);
                    var mb = GetValidBbox(mobj?.Geometry);
                    if (mb.IsValid)
                    {
                        defBbox = defBbox.IsValid ? BoundingBox.Union(defBbox, mb) : mb;
                    }
                }

                defs.Add(new Dictionary<string, object>
                {
                    ["definition_name"] = idef.Name ?? string.Empty,
                    ["definition_id"] = idef.Id.ToString(),
                    ["object_count"] = memberIds.Length,
                    ["instance_count"] = instanceCount,
                    ["bbox"] = BboxToSummaryDict(defBbox),
                });
            }
        }
        return new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["api"] = "v1_live",
            ["definition_count"] = defs.Count,
            ["definitions"] = defs,
        };
    }

    private static Dictionary<string, object> TransformedBboxDict(BoundingBox bbox, Transform xform)
    {
        // Apply a transform to a bbox by mapping its 8 corners and taking the
        // axis-aligned bounds of the result. Light (8 points), no heavy geometry
        // resolution. Returns the same shape as BboxToSummaryDict.
        if (!bbox.IsValid)
        {
            return BboxToSummaryDict(BoundingBox.Unset);
        }
        var corners = bbox.GetCorners();
        var moved = BoundingBox.Unset;
        foreach (var c in corners)
        {
            var p = c;
            p.Transform(xform);
            moved = moved.IsValid ? BoundingBox.Union(moved, new BoundingBox(p, p)) : new BoundingBox(p, p);
        }
        return BboxToSummaryDict(moved);
    }

    public Dictionary<string, object> LiveGetDefinitionObjects(
        RhinoDoc doc,
        string definitionName,
        bool resolveInstances = false)
    {
        // Return the objects that COMPOSE a block definition (1.3a: raw content, no
        // instance transform applied). This is what lets a caller read attributes/
        // text/geometry that live INSIDE a block, previously unreachable.
        //
        // When resolveInstances is true, also return one row per placed instance with
        // each member's bbox/centroid transformed by that instance's InstanceXform
        // (2.3, lightweight: only the bbox is moved, not the heavy geometry).
        var name = (definitionName ?? string.Empty).Trim();
        if (name.Length == 0)
        {
            throw new InvalidOperationException("Missing definition name.");
        }
        var table = doc.InstanceDefinitions;
        InstanceDefinition? idef = null;
        if (table is not null)
        {
            foreach (var d in table)
            {
                if (d is null || d.IsDeleted)
                {
                    continue;
                }
                if (string.Equals(d.Name ?? string.Empty, name, StringComparison.Ordinal))
                {
                    idef = d;
                    break;
                }
            }
        }
        if (idef is null)
        {
            throw new KeyNotFoundException($"Block definition not found: {name}");
        }

        var memberObjs = new List<RhinoObject>();
        var objects = new List<object>();
        foreach (var mid in idef.GetObjectIds() ?? Array.Empty<Guid>())
        {
            var mobj = doc.Objects.FindId(mid);
            if (mobj is not null)
            {
                memberObjs.Add(mobj);
                objects.Add(ExtractObject(doc, mobj));
            }
        }

        var references = Array.Empty<InstanceObject>();
        try { references = idef.GetReferences(0) ?? Array.Empty<InstanceObject>(); }
        catch { references = Array.Empty<InstanceObject>(); }

        var result = new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["api"] = "v1_live",
            ["definition_name"] = idef.Name ?? string.Empty,
            ["definition_id"] = idef.Id.ToString(),
            ["instance_count"] = references.Length,
            ["object_count"] = objects.Count,
            ["transform_applied"] = false,
            ["objects"] = objects,
        };

        if (resolveInstances)
        {
            var instances = new List<object>();
            foreach (var inst in references)
            {
                if (inst is null)
                {
                    continue;
                }
                var xform = inst.InstanceXform;
                var members = new List<object>();
                foreach (var mobj in memberObjs)
                {
                    var rawBbox = GetValidBbox(mobj.Geometry);
                    members.Add(new Dictionary<string, object>
                    {
                        ["member_object_id"] = mobj.Id.ToString(),
                        ["type"] = mobj.Geometry?.ObjectType.ToString() ?? "Unknown",
                        ["bbox"] = TransformedBboxDict(rawBbox, xform),
                    });
                }
                instances.Add(new Dictionary<string, object>
                {
                    ["instance_id"] = inst.Id.ToString(),
                    ["layer"] = LayerName(doc, inst.Attributes),
                    ["transform"] = ReadTransform(inst),
                    ["members"] = members,
                });
            }
            result["transform_applied"] = true;
            result["instances"] = instances;
        }

        return result;
    }

    // Project solids onto a plane and return 2D polygons in the plane's LOCAL (u,v)
    // coordinates. One polygon per face (Brep face loop / mesh facet), which is the
    // agnostic raw output: the client composes drawing, aperture detection (gaps
    // between projected polygons), coverage analysis — the MCP names none of those.
    //
    // Agnostic acid test (see docs/agnostic_principle.md):
    //   1. Exists in any domain?  ✓ — projecting geometry to a plane is universal.
    //   2. Needs to know what the object represents?  ✓ NO — pure geometry.
    //   3. Client can derive it from raw primitives?  ✗ — needs the kernel to map
    //      3D faces to plane space; not reconstructable from bbox alone.
    //   4. An LLM can conclude it from raw geometric data?  ✗ — cannot project exact
    //      face loops from coordinates; expose the primitive, let the LLM reason on it.
    //
    // Edge case: a face perpendicular to the plane degenerates to a line — it is
    // returned as a (near-zero-area) polygon with a per-object warning, not dropped.
    public Dictionary<string, object> ProjectToPlane(
        RhinoDoc doc,
        IReadOnlyList<string> objectIds,
        Plane plane)
    {
        if (!plane.IsValid)
        {
            throw new InvalidOperationException("project_to_plane: invalid plane (origin/normal).");
        }

        var projections = new List<object>();
        var skipped = new List<object>();

        foreach (var token in objectIds ?? Array.Empty<string>())
        {
            var obj = TryFindObject(doc, token);
            if (obj is null)
            {
                skipped.Add(new Dictionary<string, object> { ["object_id"] = token ?? string.Empty, ["reason"] = "not_found" });
                continue;
            }
            var geometry = obj.Geometry;
            var warnings = new List<object>();
            var polygons = new List<object>();

            var brep = GeometryAsBrepForElements(geometry);
            if (brep is not null)
            {
                foreach (var face in brep.Faces)
                {
                    var loop = face.OuterLoop;
                    if (loop is null) continue;
                    var loopCurve = loop.To3dCurve();
                    if (loopCurve is null) continue;
                    var poly = PolylineFromCurve(loopCurve, 64);
                    var uv = ProjectPointsToPlaneUV(poly, plane, out var degenerate);
                    if (uv.Count >= 2)
                    {
                        polygons.Add(uv);
                        if (degenerate) warnings.Add("face_perpendicular_to_plane");
                    }
                }
            }
            else if (geometry is Mesh mesh)
            {
                for (int i = 0; i < mesh.Faces.Count; i++)
                {
                    var mf = mesh.Faces[i];
                    var pts = new List<Point3d>();
                    pts.Add(mesh.Vertices[mf.A]); pts.Add(mesh.Vertices[mf.B]); pts.Add(mesh.Vertices[mf.C]);
                    if (mf.IsQuad) pts.Add(mesh.Vertices[mf.D]);
                    pts.Add(pts[0]);
                    var uv = ProjectPointsToPlaneUV(pts, plane, out var degenerate);
                    if (uv.Count >= 2)
                    {
                        polygons.Add(uv);
                        if (degenerate) warnings.Add("face_perpendicular_to_plane");
                    }
                }
            }
            else
            {
                skipped.Add(new Dictionary<string, object>
                {
                    ["object_id"] = obj.Id.ToString(),
                    ["reason"] = "not_projectable_geometry",
                    ["type"] = geometry?.ObjectType.ToString() ?? "Unknown",
                });
                continue;
            }

            // De-duplicate warnings while preserving the honest signal.
            var distinctWarnings = warnings.Select(w => (string)w).Distinct().Cast<object>().ToList();
            projections.Add(new Dictionary<string, object>
            {
                ["object_id"] = obj.Id.ToString(),
                ["polygons_2d"] = polygons,
                ["warnings"] = distinctWarnings,
            });
        }

        return new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["api"] = "v1_live",
            ["plane"] = new Dictionary<string, object>
            {
                ["origin"] = new List<double> { plane.OriginX, plane.OriginY, plane.OriginZ },
                ["normal"] = new List<double> { plane.Normal.X, plane.Normal.Y, plane.Normal.Z },
            },
            ["projection_count"] = projections.Count,
            ["projections"] = projections,
            ["skipped"] = skipped,
        };
    }

    private static List<Point3d> PolylineFromCurve(Curve curve, int count)
    {
        // Tessellate a (possibly curved) face-loop curve into points. A polyline loop
        // returns its corners; otherwise sample the domain.
        var pts = new List<Point3d>();
        if (curve is null) return pts;
        if (curve.TryGetPolyline(out var pl) && pl is not null && pl.Count >= 2)
        {
            foreach (var p in pl) pts.Add(p);
            return pts;
        }
        return SampleCurve(curve, Math.Max(8, count));
    }

    // Map 3D points to the plane's local (u,v). degenerate=true if the points'
    // spread perpendicular to the plane dominates (face nearly perpendicular -> the
    // projection collapses toward a line). Reported, not thrown.
    private static List<object> ProjectPointsToPlaneUV(IList<Point3d> pts, Plane plane, out bool degenerate)
    {
        degenerate = false;
        var uv = new List<object>();
        if (pts is null || pts.Count == 0) return uv;

        double uMin = double.MaxValue, uMax = double.MinValue, vMin = double.MaxValue, vMax = double.MinValue;
        double wMin = double.MaxValue, wMax = double.MinValue;
        foreach (var p in pts)
        {
            // (u,v) in plane; w = signed distance along the normal.
            double u = (p - plane.Origin) * plane.XAxis;
            double v = (p - plane.Origin) * plane.YAxis;
            double w = (p - plane.Origin) * plane.Normal;
            uv.Add(new List<double> { u, v });
            uMin = Math.Min(uMin, u); uMax = Math.Max(uMax, u);
            vMin = Math.Min(vMin, v); vMax = Math.Max(vMax, v);
            wMin = Math.Min(wMin, w); wMax = Math.Max(wMax, w);
        }
        var inPlaneSpan = Math.Max(uMax - uMin, vMax - vMin);
        var normalSpan = wMax - wMin;
        // Face is ~perpendicular to the plane when its in-plane footprint is tiny
        // relative to its extent along the normal.
        if (inPlaneSpan <= 1e-6 || (normalSpan > 0 && inPlaneSpan < normalSpan * 1e-3))
        {
            degenerate = true;
        }
        return uv;
    }

    // Detect REAL contacts between solids (not bbox overlap) and report WHERE the
    // contact is, not just which pair touches. The location is the whole point: it is
    // the difference between "these two pieces touch" and "the connector sits here".
    //
    // Agnostic acid test (see docs/agnostic_principle.md):
    //   1. Exists in any domain?  ✓ — "two solids touch here" is meaningful for a
    //      mechanical assembly, a 3D character, an anatomy scan; nothing about wood.
    //   2. Needs to know what the object represents?  ✓ NO — it operates on raw breps;
    //      it never asks "is this a stud / a plate / a connector".
    //   3. Client can derive it from raw primitives?  ✗ — requires a geometry engine
    //      (brep-brep intersection); the client cannot compute it from bbox/edges alone.
    //   4. An LLM can conclude it from raw geometric data?  ✗ — an LLM cannot run
    //      exact brep intersection from coordinates, so this is a primitive to expose,
    //      not a use to bake in. (Deducing "extremity" / "joint" / "graph" FROM these
    //      contacts is the LLM's job — those would be leaks.)
    //
    // contact_type:
    //   "point"   -> contact_point          (touching at a vertex/edge tip)
    //   "curve"   -> contact_curve (polyline samples) (touching along an edge/seam)
    //   "surface" -> contact_region_bbox + approx_area (face-on-face overlap)
    //
    // Performance: broad phase filters pairs by padded-AABB overlap (cheap) before the
    // expensive brep-brep intersection, so it scales to large object sets — the caller
    // already bounds the work by passing the object_ids of interest.
    public Dictionary<string, object> ComputeContacts(
        RhinoDoc doc,
        IReadOnlyList<string> objectIds,
        double tolerance)
    {
        var tol = tolerance > 0 && !double.IsNaN(tolerance) && !double.IsInfinity(tolerance)
            ? tolerance
            : 1e-3;

        // Resolve requested objects to (id, brep, padded bbox). Non-brep / missing are
        // reported in `skipped` so the result is honest about what was evaluated.
        var items = new List<(string Id, Brep Brep, BoundingBox Box)>();
        var skipped = new List<object>();
        foreach (var token in objectIds ?? Array.Empty<string>())
        {
            var obj = TryFindObject(doc, token);
            if (obj is null)
            {
                skipped.Add(new Dictionary<string, object> { ["object_id"] = token ?? string.Empty, ["reason"] = "not_found" });
                continue;
            }
            var brep = AsBrep(obj.Geometry);
            if (brep is null)
            {
                skipped.Add(new Dictionary<string, object>
                {
                    ["object_id"] = obj.Id.ToString(),
                    ["reason"] = "not_a_solid_brep",
                    ["type"] = obj.Geometry?.ObjectType.ToString() ?? "Unknown",
                });
                continue;
            }
            var box = GetValidBbox(brep);
            if (!box.IsValid)
            {
                skipped.Add(new Dictionary<string, object> { ["object_id"] = obj.Id.ToString(), ["reason"] = "no_valid_bbox" });
                continue;
            }
            box.Inflate(tol);
            items.Add((obj.Id.ToString(), brep, box));
        }

        var contacts = new List<object>();
        var pairsTested = 0;
        for (int i = 0; i < items.Count; i++)
        {
            for (int j = i + 1; j < items.Count; j++)
            {
                // Broad phase: skip pairs whose (padded) bboxes do not overlap.
                if (!BboxesIntersect(items[i].Box, items[j].Box))
                {
                    continue;
                }
                pairsTested++;
                var contact = EvaluateBrepContact(items[i].Id, items[i].Brep, items[j].Id, items[j].Brep, tol);
                if (contact is not null)
                {
                    contacts.Add(contact);
                }
            }
        }

        return new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["api"] = "v1_live",
            ["tolerance"] = tol,
            ["evaluated_count"] = items.Count,
            ["pairs_tested"] = pairsTested,
            ["contact_count"] = contacts.Count,
            ["contacts"] = contacts,
            ["skipped"] = skipped,
        };
    }

    private static Brep? AsBrep(GeometryBase? geometry)
    {
        if (geometry is Brep brep)
        {
            return brep;
        }
        if (geometry is Extrusion ext)
        {
            try { return ext.ToBrep(true); } catch { return null; }
        }
        if (geometry is Surface srf)
        {
            try { return srf.ToBrep(); } catch { return null; }
        }
        return null;
    }

    private static Dictionary<string, object>? EvaluateBrepContact(
        string idA, Brep a, string idB, Brep b, double tol)
    {
        Curve[]? curves = null;
        Point3d[]? points = null;
        bool ok;
        try
        {
            ok = Intersection.BrepBrep(a, b, tol, out curves, out points);
        }
        catch
        {
            return null;
        }
        if (!ok)
        {
            return null;
        }

        var curveList = curves ?? Array.Empty<Curve>();
        var pointList = points ?? Array.Empty<Point3d>();
        if (curveList.Length == 0 && pointList.Length == 0)
        {
            return null;
        }

        // Gather all intersection geometry to a single bounding region, used to decide
        // point vs curve vs surface and to report the contact location.
        var region = BoundingBox.Unset;
        double totalCurveLength = 0.0;
        var polylineSamples = new List<object>();
        foreach (var c in curveList)
        {
            if (c is null) continue;
            var cb = c.GetBoundingBox(true);
            if (cb.IsValid) region = region.IsValid ? BoundingBox.Union(region, cb) : cb;
            try { totalCurveLength += c.GetLength(); } catch { }
            foreach (var p in SampleCurve(c, 12))
            {
                polylineSamples.Add(new List<double> { p.X, p.Y, p.Z });
            }
        }
        foreach (var p in pointList)
        {
            region = region.IsValid ? BoundingBox.Union(region, new BoundingBox(p, p)) : new BoundingBox(p, p);
        }

        // Classify. A surface contact (face-on-face) shows up as closed/area-bounding
        // intersection curves: if the intersection curves enclose a measurable planar
        // area, report it as surface with region bbox + approx_area. Otherwise, curves
        // -> curve contact; only points -> point contact.
        var diag = region.IsValid ? region.Diagonal : new Vector3d(0, 0, 0);
        double regionArea = EstimatePlanarContactArea(curveList);

        var result = new Dictionary<string, object>
        {
            ["pair"] = new List<object> { idA, idB },
            ["contact_point"] = null!,
            ["contact_curve"] = null!,
            ["contact_region_bbox"] = null!,
        };

        if (regionArea > tol * tol && curveList.Length > 0)
        {
            result["contact_type"] = "surface";
            result["contact_region_bbox"] = BboxMinMaxOnly(region);
            result["approx_area"] = regionArea;
        }
        else if (curveList.Length > 0)
        {
            result["contact_type"] = "curve";
            result["contact_curve"] = polylineSamples;
            result["approx_area"] = 0.0;
        }
        else
        {
            result["contact_type"] = "point";
            var p0 = pointList[0];
            result["contact_point"] = new List<double> { p0.X, p0.Y, p0.Z };
            result["approx_area"] = 0.0;
        }
        return result;
    }

    private static List<Point3d> SampleCurve(Curve curve, int count)
    {
        var pts = new List<Point3d>();
        if (curve is null) return pts;
        count = Math.Max(2, count);
        try
        {
            var dom = curve.Domain;
            for (int k = 0; k < count; k++)
            {
                var t = dom.ParameterAt(k / (double)(count - 1));
                pts.Add(curve.PointAt(t));
            }
        }
        catch
        {
            // Fall back to endpoints if parameterization fails.
            try { pts.Add(curve.PointAtStart); pts.Add(curve.PointAtEnd); } catch { }
        }
        return pts;
    }

    // Approximate the area enclosed by intersection curves. Face-on-face contact yields
    // closed boundary curves; their planar area is the contact patch. Open curves
    // (edge seams) enclose ~0, which keeps them classified as "curve". Best-effort:
    // joins curve fragments, then sums planar areas of the resulting closed loops.
    private static double EstimatePlanarContactArea(Curve[] curves)
    {
        if (curves is null || curves.Length == 0)
        {
            return 0.0;
        }
        try
        {
            var joined = Curve.JoinCurves(curves.Where(c => c is not null), 1e-3) ?? Array.Empty<Curve>();
            double area = 0.0;
            foreach (var c in joined)
            {
                if (c is null || !c.IsClosed) continue;
                var amp = AreaMassProperties.Compute(c);
                if (amp is not null && !double.IsNaN(amp.Area))
                {
                    area += Math.Abs(amp.Area);
                }
            }
            return area;
        }
        catch
        {
            return 0.0;
        }
    }

    public Dictionary<string, object> ExtractScene(RhinoDoc doc)
    {
        var objects = doc.Objects
            .Select(o => ExtractObject(doc, o))
            .Cast<object>()
            .ToList();
        return new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["object_count"] = objects.Count,
            ["objects"] = objects
        };
    }

    public Dictionary<string, object> ExtractObjects(RhinoDoc doc, IReadOnlyList<string> objectIds)
    {
        if (objectIds is null || objectIds.Count == 0)
        {
            throw new InvalidOperationException("No object ids provided. Use object_ids in query or JSON body.");
        }

        var extracted = new List<object>();
        var missing = new List<object>();
        foreach (var token in objectIds)
        {
            var normalized = (token ?? string.Empty).Trim();
            if (normalized.StartsWith("obj:", StringComparison.OrdinalIgnoreCase))
            {
                normalized = normalized.Substring(4);
            }
            if (!Guid.TryParse(normalized, out var guid))
            {
                missing.Add(new Dictionary<string, object>
                {
                    ["object_id"] = token ?? string.Empty,
                    ["reason"] = "invalid_guid"
                });
                continue;
            }

            var obj = doc.Objects.FindId(guid);
            if (obj is null)
            {
                missing.Add(new Dictionary<string, object>
                {
                    ["object_id"] = token ?? string.Empty,
                    ["reason"] = "not_found"
                });
                continue;
            }
            extracted.Add(ExtractObject(doc, obj));
        }

        return new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["requested_count"] = objectIds.Count,
            ["object_count"] = extracted.Count,
            ["objects"] = extracted,
            ["missing"] = missing
        };
    }

    public Dictionary<string, object> VerifyRelations(
        RhinoDoc doc,
        IReadOnlyList<RelationVerificationRequest> relations,
        VerificationTolerance tolerance)
    {
        if (relations is null || relations.Count == 0)
        {
            throw new InvalidOperationException("No relations provided for verification.");
        }
        var results = new List<object>();
        foreach (var rel in relations)
        {
            results.Add(VerifySingleRelation(doc, rel, tolerance));
        }
        return new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["results"] = results
        };
    }

    private static Dictionary<string, object> VerifySingleRelation(
        RhinoDoc doc,
        RelationVerificationRequest rel,
        VerificationTolerance tolerance)
    {
        var relationId = rel.RelationId ?? string.Empty;
        var subjectId = rel.SubjectId ?? string.Empty;
        var objectId = rel.ObjectId ?? string.Empty;
        var check = (rel.Check ?? string.Empty).Trim().ToLowerInvariant();
        var linearTol = Math.Max(0.0, tolerance.LinearTolerance);

        var measurements = new Dictionary<string, object?>
        {
            ["distance"] = null,
            ["intersection_count"] = 0,
            ["contact_area_estimate"] = null
        };
        var limitations = new List<object>();
        var notes = new List<object>();

        var subjectObj = TryFindObject(doc, subjectId);
        var objectObj = TryFindObject(doc, objectId);
        if (subjectObj is null || objectObj is null)
        {
            limitations.Add("object_not_found_for_verification");
            return BuildVerificationResult(
                relationId,
                subjectId,
                objectId,
                check,
                "inconclusive",
                "candidate",
                "tolerance_review",
                measurements,
                0.2,
                limitations,
                notes);
        }

        var gA = subjectObj.Geometry;
        var gB = objectObj.Geometry;
        var bboxA = GetValidBbox(gA);
        var bboxB = GetValidBbox(gB);
        var bboxGap = ComputeBoundingBoxGap(bboxA, bboxB);
        measurements["distance"] = bboxGap;

        switch (check)
        {
            case "mesh_distance_check":
            {
                var method = "mesh_distance";
                if (gA is Brep && gB is Brep)
                {
                    method = "brep_closest_point";
                    notes.Add("distance estimated from bbox proxy when exact closest-point unavailable");
                }
                if (bboxGap <= linearTol)
                {
                    return BuildVerificationResult(
                        relationId, subjectId, objectId, check,
                        "verified", "confirmed", method, measurements, 0.88, limitations, notes);
                }
                return BuildVerificationResult(
                    relationId, subjectId, objectId, check,
                    "contradicted", "measured", method, measurements, 0.75, limitations, notes);
            }
            case "brep_contact_check":
            {
                var distance = bboxGap;
                if (double.IsNaN(distance) || double.IsInfinity(distance))
                {
                    limitations.Add("contact_distance_unavailable");
                    return BuildVerificationResult(
                        relationId, subjectId, objectId, check,
                        "inconclusive", "candidate", "brep_contact_check", measurements, 0.3, limitations, notes);
                }

                if (distance <= linearTol)
                {
                    var method = (gA is Brep && gB is Brep) ? "brep_closest_point" : "brep_contact_check";
                    return BuildVerificationResult(
                        relationId, subjectId, objectId, check,
                        "verified", "confirmed", method, measurements, 0.85, limitations, notes);
                }
                return BuildVerificationResult(
                    relationId, subjectId, objectId, check,
                    "contradicted", "measured", "brep_contact_check", measurements, 0.75, limitations, notes);
            }
            case "brep_intersection_check":
            {
                if (gA is Brep brepA && gB is Brep brepB)
                {
                    try
                    {
                        var ok = Intersection.BrepBrep(brepA, brepB, linearTol, out var curves, out var points);
                        var count = (curves?.Length ?? 0) + (points?.Length ?? 0);
                        measurements["intersection_count"] = count;
                        if (ok && count > 0)
                        {
                            return BuildVerificationResult(
                                relationId, subjectId, objectId, check,
                                "verified", "confirmed", "brep_intersection_curve", measurements, 0.92, limitations, notes);
                        }
                        return BuildVerificationResult(
                            relationId, subjectId, objectId, check,
                            "contradicted", "measured", "brep_intersection_curve", measurements, 0.72, limitations, notes);
                    }
                    catch
                    {
                        limitations.Add("brep_intersection_unavailable");
                    }
                }
                else
                {
                    limitations.Add("brep_intersection_unavailable");
                }
                return BuildVerificationResult(
                    relationId, subjectId, objectId, check,
                    "inconclusive", "candidate", "brep_intersection_curve", measurements, 0.35, limitations, notes);
            }
            case "face_adjacency_check":
            {
                limitations.Add("face_adjacency_exact_check_not_implemented");
                return BuildVerificationResult(
                    relationId, subjectId, objectId, check,
                    "inconclusive", "candidate", "tolerance_review", measurements, 0.3, limitations, notes);
            }
            case "tolerance_review":
            {
                if (bboxGap <= linearTol)
                {
                    return BuildVerificationResult(
                        relationId, subjectId, objectId, check,
                        "verified", "measured", "tolerance_review", measurements, 0.8, limitations, notes);
                }
                return BuildVerificationResult(
                    relationId, subjectId, objectId, check,
                    "contradicted", "measured", "tolerance_review", measurements, 0.7, limitations, notes);
            }
            default:
                limitations.Add("unsupported_check");
                return BuildVerificationResult(
                    relationId, subjectId, objectId, check,
                    "inconclusive", "candidate", "tolerance_review", measurements, 0.2, limitations, notes);
        }
    }

    private static Dictionary<string, object> BuildVerificationResult(
        string relationId,
        string subjectId,
        string objectId,
        string check,
        string verificationStatus,
        string assertionLevel,
        string method,
        Dictionary<string, object?> measurements,
        double confidence,
        List<object> limitations,
        List<object> notes)
    {
        return new Dictionary<string, object>
        {
            ["relation_id"] = relationId,
            ["subject_id"] = subjectId,
            ["object_id"] = objectId,
            ["check"] = check,
            ["verification_status"] = verificationStatus,
            ["assertion_level"] = assertionLevel,
            ["method"] = method,
            ["measurements"] = measurements.ToDictionary(k => k.Key, v => v.Value ?? (object?)null),
            ["confidence"] = Math.Max(0.0, Math.Min(1.0, confidence)),
            ["limitations"] = limitations,
            ["notes"] = notes
        };
    }

    private static RhinoObject? TryFindObject(RhinoDoc doc, string objectId)
    {
        var token = (objectId ?? string.Empty).Trim();
        if (token.StartsWith("obj:", StringComparison.OrdinalIgnoreCase))
        {
            token = token.Substring(4);
        }
        if (!Guid.TryParse(token, out var guid))
        {
            return null;
        }
        return doc.Objects.FindId(guid);
    }

    private static double ComputeBoundingBoxGap(BoundingBox a, BoundingBox b)
    {
        if (!a.IsValid || !b.IsValid)
        {
            return double.PositiveInfinity;
        }
        var gapSq = 0.0;
        if (a.Max.X < b.Min.X) gapSq += Math.Pow(b.Min.X - a.Max.X, 2);
        else if (b.Max.X < a.Min.X) gapSq += Math.Pow(a.Min.X - b.Max.X, 2);
        if (a.Max.Y < b.Min.Y) gapSq += Math.Pow(b.Min.Y - a.Max.Y, 2);
        else if (b.Max.Y < a.Min.Y) gapSq += Math.Pow(a.Min.Y - b.Max.Y, 2);
        if (a.Max.Z < b.Min.Z) gapSq += Math.Pow(b.Min.Z - a.Max.Z, 2);
        else if (b.Max.Z < a.Min.Z) gapSq += Math.Pow(a.Min.Z - b.Max.Z, 2);
        return Math.Sqrt(Math.Max(0.0, gapSq));
    }

    private static Dictionary<string, object>? ReadAnnotationText(GeometryBase? geometry)
    {
        // Resolve the textual content of annotations (text, dimensions, leaders).
        // Domain-agnostic: we expose the plain text as data; we do not interpret it.
        // Returns null for non-annotation geometry. Defensive: any RhinoCommon
        // version/shape mismatch degrades to null rather than throwing.
        if (geometry is null)
        {
            return null;
        }
        try
        {
            string? plain = null;
            string? rich = null;
            string kind = geometry.GetType().Name;

            if (geometry is TextEntity textEntity)
            {
                plain = textEntity.PlainText;
                rich = textEntity.RichText;
            }
            else if (geometry is AnnotationBase annotation)
            {
                // Dimensions, leaders, etc. PlainText resolves fields where possible.
                plain = annotation.PlainText;
                try { rich = annotation.RichText; } catch { rich = null; }
            }
            else if (geometry is TextDot dot)
            {
                plain = dot.Text;
            }
            else
            {
                return null;
            }

            var result = new Dictionary<string, object>
            {
                ["kind"] = kind,
                ["plain_text"] = plain ?? string.Empty,
            };
            if (!string.IsNullOrEmpty(rich) && rich != plain)
            {
                result["rich_text"] = rich!;
            }
            return result;
        }
        catch
        {
            return null;
        }
    }

    private static Dictionary<string, object> ExtractObject(RhinoDoc doc, RhinoObject obj)
    {
        var attrs = obj.Attributes;
        var geometry = obj.Geometry;
        var bbox = GetValidBbox(geometry);
        var groupIds = attrs.GetGroupList() ?? Array.Empty<int>();
        var groupNames = groupIds
            .Select(id => GroupName(doc, id))
            .Cast<object>()
            .ToList();

        var isBlockInstance = obj is InstanceObject || geometry?.ObjectType == ObjectType.InstanceReference;
        var definitionName = string.Empty;
        if (obj is InstanceObject instanceObject)
        {
            definitionName = instanceObject.InstanceDefinition?.Name ?? string.Empty;
        }

        var result = new Dictionary<string, object>
        {
            ["object_id"] = obj.Id.ToString(),
            ["type"] = geometry?.ObjectType.ToString() ?? "Unknown",
            ["name"] = (attrs.Name ?? string.Empty).Trim(),
            ["layer"] = LayerName(doc, attrs),
            ["group_ids"] = groupIds.Select(id => id.ToString(CultureInfo.InvariantCulture)).Cast<object>().ToList(),
            ["group_names"] = groupNames,
            ["user_text"] = ReadUserText(attrs).ToDictionary(k => k.Key, v => (object)v.Value),
            ["material"] = ReadMaterial(doc, attrs),
            ["transform"] = ReadTransform(obj),
            ["block_info"] = new Dictionary<string, object>
            {
                ["is_block_instance"] = isBlockInstance,
                ["definition_name"] = definitionName,
                ["instance_id"] = isBlockInstance ? obj.Id.ToString() : string.Empty
            },
            ["raw_geometry_summary"] = BuildRawGeometrySummary(geometry, bbox)
        };

        var annotationText = ReadAnnotationText(geometry);
        if (annotationText is not null)
        {
            result["annotation_text"] = annotationText;
        }
        return result;
    }

    // Oriented bounding box, expressed as its three side lengths sorted descending.
    // Domain-agnostic: these are the intrinsic extents of the solid regardless of how
    // it is rotated in world space, unlike the world-axis-aligned bbox. The caller
    // decides what each dimension means (e.g. "the longest is the cut length").
    //
    // Strategy (no external dependency, best-effort):
    //   - Brep/Extrusion/Mesh/Surface: try planes aligned to each face normal and to
    //     the world axes; keep the box of smallest volume. This recovers the true
    //     extents of prismatic / axis-tilted parts that the AABB inflates.
    //   - Curve: the OBB of a planar/linear curve via its own plane when available.
    //   - Anything else / failure: fall back to the world AABB extents.
    private static List<double>? ComputeObbDimensions(GeometryBase? geometry, BoundingBox aabb)
    {
        try
        {
            var planes = new List<Plane> { Plane.WorldXY };
            if (geometry is Brep brep)
            {
                foreach (var face in brep.Faces)
                {
                    var u = face.Domain(0).Mid;
                    var v = face.Domain(1).Mid;
                    if (face.FrameAt(u, v, out var fr))
                    {
                        planes.Add(fr);
                    }
                }
            }
            else if (geometry is Curve curve && curve.TryGetPlane(out var cpl))
            {
                planes.Add(cpl);
            }

            BoundingBox best = BoundingBox.Unset;
            double bestVol = double.PositiveInfinity;
            foreach (var pl in planes)
            {
                if (!pl.IsValid) continue;
                var box = geometry?.GetBoundingBox(pl) ?? BoundingBox.Unset;
                if (!box.IsValid) continue;
                var d = box.Diagonal;
                var vol = Math.Abs(d.X) * Math.Abs(d.Y) * Math.Abs(d.Z);
                // For flat parts (zero-thickness) compare by face area instead of volume.
                if (vol <= 1e-12) vol = Math.Abs(d.X) * Math.Abs(d.Y) + Math.Abs(d.Y) * Math.Abs(d.Z) + Math.Abs(d.X) * Math.Abs(d.Z);
                if (vol < bestVol) { bestVol = vol; best = box; }
            }

            var source = best.IsValid ? best : aabb;
            if (!source.IsValid) return null;
            var dia = source.Diagonal;
            var dims = new List<double> { Math.Abs(dia.X), Math.Abs(dia.Y), Math.Abs(dia.Z) };
            dims.Sort();
            dims.Reverse(); // descending: [longest, mid, shortest]
            return dims;
        }
        catch
        {
            if (!aabb.IsValid) return null;
            var dia = aabb.Diagonal;
            var dims = new List<double> { Math.Abs(dia.X), Math.Abs(dia.Y), Math.Abs(dia.Z) };
            dims.Sort();
            dims.Reverse();
            return dims;
        }
    }

    // Length of the single longest edge of a solid/surface. For a prismatic part
    // (beam, stud, board) this is the real cut length even when the part runs in a
    // diagonal — the world-axis bbox cannot recover this. Agnostic: just the max
    // edge length; the caller assigns meaning. Null for geometry without edges.
    private static double? ComputeLongestEdge(GeometryBase? geometry)
    {
        try
        {
            if (geometry is Brep brep)
            {
                double max = 0.0;
                bool any = false;
                foreach (var edge in brep.Edges)
                {
                    var len = edge.GetLength();
                    if (len > 0 && !double.IsNaN(len) && !double.IsInfinity(len))
                    {
                        any = true;
                        if (len > max) max = len;
                    }
                }
                return any ? max : (double?)null;
            }
            if (geometry is Extrusion ext)
            {
                return ComputeLongestEdge(ext.ToBrep(false));
            }
            if (geometry is Mesh mesh)
            {
                double max = 0.0;
                bool any = false;
                var te = mesh.TopologyEdges;
                for (int i = 0; i < te.Count; i++)
                {
                    var line = te.EdgeLine(i);
                    var len = line.Length;
                    if (len > 0 && !double.IsNaN(len) && !double.IsInfinity(len))
                    {
                        any = true;
                        if (len > max) max = len;
                    }
                }
                return any ? max : (double?)null;
            }
            return null;
        }
        catch
        {
            return null;
        }
    }

    private static Dictionary<string, object> BuildRawGeometrySummary(GeometryBase? geometry, BoundingBox bbox)
    {
        var faceAreas = new List<object>();
        var faceNormals = new List<object>();
        var faceCount = 0;
        var edgeCount = 0;
        bool? isClosed = null;
        double? volume = null;
        double? area = null;

        if (geometry is Brep brep)
        {
            faceCount = brep.Faces.Count;
            edgeCount = brep.Edges.Count;
            isClosed = brep.IsSolid;
            foreach (var face in brep.Faces)
            {
                var amp = AreaMassProperties.Compute(face);
                if (amp is not null)
                {
                    faceAreas.Add(amp.Area);
                }
                var u = face.Domain(0).Mid;
                var v = face.Domain(1).Mid;
                var n = face.NormalAt(u, v);
                if (!n.IsTiny(1e-9))
                {
                    n.Unitize();
                }
                faceNormals.Add(new List<double> { n.X, n.Y, n.Z });
            }
        }
        else if (geometry is Mesh mesh)
        {
            faceCount = mesh.Faces.Count;
            edgeCount = mesh.TopologyEdges.Count;
            isClosed = mesh.IsClosed;
        }
        double? length = null;
        if (geometry is Curve curve)
        {
            edgeCount = 1;
            isClosed = curve.IsClosed;
            try
            {
                var len = curve.GetLength();
                if (len > 0 && !double.IsNaN(len) && !double.IsInfinity(len))
                {
                    length = len;
                }
            }
            catch { length = null; }
        }

        volume = ComputeVolume(geometry);
        area = ComputeArea(geometry);

        var corners = bbox.IsValid
            ? bbox.GetCorners().Select(p => (object)new List<double> { p.X, p.Y, p.Z }).ToList()
            : new List<object>();
        var samplePoints = BuildSamplePoints(bbox, 6);

        var obb = ComputeObbDimensions(geometry, bbox);
        var longestEdge = ComputeLongestEdge(geometry);

        var summary = new Dictionary<string, object>
        {
            ["bbox"] = bbox.IsValid
                ? new Dictionary<string, object>
                {
                    ["min"] = new List<double> { bbox.Min.X, bbox.Min.Y, bbox.Min.Z },
                    ["max"] = new List<double> { bbox.Max.X, bbox.Max.Y, bbox.Max.Z },
                    ["center"] = new List<double> { bbox.Center.X, bbox.Center.Y, bbox.Center.Z }
                }
                : new Dictionary<string, object>(),
            ["bbox_corners"] = corners,
            ["sample_points"] = samplePoints,
            ["face_count"] = faceCount,
            ["face_areas"] = faceAreas,
            ["face_normals"] = faceNormals,
            ["edge_count"] = edgeCount,
            ["is_closed"] = isClosed.HasValue ? (object)isClosed.Value : null!,
            ["volume"] = volume.HasValue ? (object)volume.Value : null!,
            ["area"] = area.HasValue ? (object)area.Value : null!,
            ["length"] = length.HasValue ? (object)length.Value : null!,
            ["source"] = "rhino_bridge"
        };
        if (obb is not null)
        {
            // Oriented extents sorted descending: [longest, mid, shortest]. Named
            // generically (not "length/width/height") to avoid implying a domain role.
            summary["obb_dimensions"] = obb.Cast<object>().ToList();
            summary["obb_longest"] = obb[0];
            summary["obb_mid"] = obb[1];
            summary["obb_shortest"] = obb[2];
        }
        if (longestEdge.HasValue)
        {
            summary["longest_edge"] = longestEdge.Value;
        }
        return summary;
    }

    private static List<object> BuildSamplePoints(BoundingBox bbox, int targetCount)
    {
        var points = new List<Point3d>();
        if (bbox.IsValid)
        {
            points.Add(bbox.Center);
            points.AddRange(bbox.GetCorners());
        }
        if (points.Count == 0)
        {
            points.Add(Point3d.Origin);
        }
        var unique = points
            .GroupBy(p => $"{Math.Round(p.X, 6)}|{Math.Round(p.Y, 6)}|{Math.Round(p.Z, 6)}")
            .Select(g => g.First())
            .Take(Math.Max(3, Math.Min(10, targetCount)))
            .Select(p => (object)new List<double> { p.X, p.Y, p.Z })
            .ToList();

        while (unique.Count < 3)
        {
            unique.Add(new List<double> { 0.0, 0.0, 0.0 });
        }
        return unique;
    }

    private static double? ComputeVolume(GeometryBase? geometry)
    {
        if (geometry is Brep brep)
        {
            return VolumeMassProperties.Compute(brep)?.Volume;
        }
        if (geometry is Mesh mesh)
        {
            return VolumeMassProperties.Compute(mesh)?.Volume;
        }
        if (geometry is Surface surface)
        {
            return VolumeMassProperties.Compute(surface)?.Volume;
        }
        if (geometry is Extrusion extrusion)
        {
            return VolumeMassProperties.Compute(extrusion)?.Volume;
        }
        return null;
    }

    private static double? ComputeArea(GeometryBase? geometry)
    {
        if (geometry is Brep brep)
        {
            return AreaMassProperties.Compute(brep)?.Area;
        }
        if (geometry is Mesh mesh)
        {
            return AreaMassProperties.Compute(mesh)?.Area;
        }
        if (geometry is Surface surface)
        {
            return AreaMassProperties.Compute(surface)?.Area;
        }
        if (geometry is Curve curve)
        {
            return AreaMassProperties.Compute(curve)?.Area;
        }
        if (geometry is Hatch hatch)
        {
            return AreaMassProperties.Compute(hatch)?.Area;
        }
        if (geometry is Extrusion extrusion)
        {
            return AreaMassProperties.Compute(extrusion)?.Area;
        }
        return null;
    }

    private static string LayerName(RhinoDoc doc, ObjectAttributes attrs)
    {
        return doc.Layers[attrs.LayerIndex]?.FullPath ?? "Unassigned";
    }

    private static string GroupName(RhinoDoc doc, int groupId)
    {
        try
        {
            return doc.Groups.GroupName(groupId) ?? string.Empty;
        }
        catch
        {
            return string.Empty;
        }
    }

    private static string ReadMaterial(RhinoDoc doc, ObjectAttributes attrs)
    {
        if (attrs.MaterialIndex >= 0 && attrs.MaterialIndex < doc.Materials.Count)
        {
            return doc.Materials[attrs.MaterialIndex]?.Name ?? string.Empty;
        }
        return string.Empty;
    }

    private static List<object> ReadTransform(RhinoObject obj)
    {
        Transform xform = Transform.Identity;
        if (obj is InstanceObject instanceObject)
        {
            xform = instanceObject.InstanceXform;
        }

        return new List<object>
        {
            RowToList(xform, 0),
            RowToList(xform, 1),
            RowToList(xform, 2),
            RowToList(xform, 3)
        };
    }

    private static List<double> RowToList(Transform xform, int row)
    {
        return new List<double>
        {
            xform[row, 0],
            xform[row, 1],
            xform[row, 2],
            xform[row, 3]
        };
    }

    private static BoundingBox GetValidBbox(GeometryBase? geometry)
    {
        if (geometry is null)
        {
            return BoundingBox.Unset;
        }
        var bbox = geometry.GetBoundingBox(true);
        if (!bbox.IsValid)
        {
            bbox = geometry.GetBoundingBox(false);
        }
        return bbox;
    }

    private static Dictionary<string, object> BboxToSummaryDict(BoundingBox bbox)
    {
        if (!bbox.IsValid)
        {
            return new Dictionary<string, object>();
        }
        return new Dictionary<string, object>
        {
            ["min"] = new List<double> { bbox.Min.X, bbox.Min.Y, bbox.Min.Z },
            ["max"] = new List<double> { bbox.Max.X, bbox.Max.Y, bbox.Max.Z },
            ["center"] = new List<double> { bbox.Center.X, bbox.Center.Y, bbox.Center.Z }
        };
    }

    private static Dictionary<string, object> ExtractObjectLiveLight(RhinoDoc doc, RhinoObject obj, string userTextMode)
    {
        var attrs = obj.Attributes;
        var geometry = obj.Geometry;
        var bbox = GetValidBbox(geometry);
        var groupIds = attrs.GetGroupList() ?? Array.Empty<int>();
        var map = new Dictionary<string, object>
        {
            ["object_id"] = obj.Id.ToString(),
            ["type"] = geometry?.ObjectType.ToString() ?? "Unknown",
            ["name"] = (attrs.Name ?? string.Empty).Trim(),
            ["layer"] = LayerName(doc, attrs),
            ["group_ids"] = groupIds.Select(id => id.ToString(CultureInfo.InvariantCulture)).Cast<object>().ToList(),
            ["bbox"] = BboxMinMaxOnly(bbox)
        };
        ApplyUserTextModeToMap(map, attrs, userTextMode);
        return map;
    }

    private static Dictionary<string, object> BboxMinMaxOnly(BoundingBox bbox)
    {
        if (!bbox.IsValid)
        {
            return new Dictionary<string, object>();
        }
        return new Dictionary<string, object>
        {
            ["min"] = new List<double> { bbox.Min.X, bbox.Min.Y, bbox.Min.Z },
            ["max"] = new List<double> { bbox.Max.X, bbox.Max.Y, bbox.Max.Z }
        };
    }

    private static void ApplyUserTextModeToMap(Dictionary<string, object> map, ObjectAttributes attrs, string mode)
    {
        mode = (mode ?? "full").Trim().ToLowerInvariant();
        var raw = ReadUserText(attrs);
        switch (mode)
        {
            case "none":
                map["user_text"] = new Dictionary<string, object>();
                break;
            case "keys":
                map["user_text"] = raw.Keys
                    .OrderBy(k => k, StringComparer.OrdinalIgnoreCase)
                    .ToDictionary(k => k, _ => (object)string.Empty);
                break;
            default:
                map["user_text"] = raw.ToDictionary(k => k.Key, v => (object)v.Value);
                break;
        }
    }

    private static BoundingBox? TryParseFilterBbox(LiveBboxFilter? f)
    {
        if (f?.Min is null || f.Max is null || f.Min.Count < 3 || f.Max.Count < 3)
        {
            return null;
        }
        try
        {
            var min = new Point3d(f.Min[0], f.Min[1], f.Min[2]);
            var max = new Point3d(f.Max[0], f.Max[1], f.Max[2]);
            var box = new BoundingBox(min, max);
            return box.IsValid ? box : null;
        }
        catch
        {
            return null;
        }
    }

    private static HashSet<string>? NormalizeFilterList(List<string>? list)
    {
        if (list is null || list.Count == 0)
        {
            return null;
        }
        return new HashSet<string>(
            list.Select(v => (v ?? string.Empty).Trim()).Where(v => v.Length > 0),
            StringComparer.OrdinalIgnoreCase);
    }

    private static bool PassesLiveFilters(
        RhinoDoc doc,
        RhinoObject obj,
        HashSet<string>? layerSet,
        HashSet<string>? typeSet,
        string nameNeedle,
        bool? hasUserText,
        string utKey,
        string? utVal,
        BoundingBox? filterBbox)
    {
        var attrs = obj.Attributes;
        var geometry = obj.Geometry;
        var typeName = geometry?.ObjectType.ToString() ?? "Unknown";
        if (typeSet is not null && !typeSet.Contains(typeName))
        {
            return false;
        }
        var layerPath = LayerName(doc, attrs);
        if (layerSet is not null && !layerSet.Contains(layerPath))
        {
            return false;
        }
        var name = (attrs.Name ?? string.Empty).Trim();
        if (nameNeedle.Length > 0 && name.IndexOf(nameNeedle, StringComparison.OrdinalIgnoreCase) < 0)
        {
            return false;
        }
        var ut = ReadUserText(attrs);
        if (hasUserText.HasValue)
        {
            var any = ut.Count > 0;
            if (hasUserText.Value != any)
            {
                return false;
            }
        }
        if (utKey.Length > 0)
        {
            if (!ut.TryGetValue(utKey, out var found))
            {
                return false;
            }
            if (utVal is not null && !string.Equals(found, utVal, StringComparison.Ordinal))
            {
                return false;
            }
        }
        else if (utVal is not null && utVal.Length > 0)
        {
            if (!ut.Values.Any(v => string.Equals(v, utVal, StringComparison.Ordinal)))
            {
                return false;
            }
        }
        if (filterBbox.HasValue)
        {
            var ob = GetValidBbox(geometry);
            if (!ob.IsValid)
            {
                return false;
            }
            if (!BboxesIntersect(ob, filterBbox.Value))
            {
                return false;
            }
        }
        return true;
    }

    private static bool BboxesIntersect(BoundingBox a, BoundingBox b)
    {
        if (!a.IsValid || !b.IsValid)
        {
            return false;
        }
        if (a.Max.X < b.Min.X || b.Max.X < a.Min.X)
        {
            return false;
        }
        if (a.Max.Y < b.Min.Y || b.Max.Y < a.Min.Y)
        {
            return false;
        }
        if (a.Max.Z < b.Min.Z || b.Max.Z < a.Min.Z)
        {
            return false;
        }
        return true;
    }

    private static HashSet<string>? NormalizeFieldSet(List<string>? fields)
    {
        if (fields is null || fields.Count == 0)
        {
            return null;
        }
        return new HashSet<string>(
            fields.Select(f => (f ?? string.Empty).Trim().ToLowerInvariant()).Where(f => f.Length > 0),
            StringComparer.OrdinalIgnoreCase);
    }

    private static Dictionary<string, object> BuildQueryObjectRow(RhinoDoc doc, RhinoObject obj, HashSet<string>? fields)
    {
        var attrs = obj.Attributes;
        var geometry = obj.Geometry;
        var bbox = GetValidBbox(geometry);
        var groupIds = attrs.GetGroupList() ?? Array.Empty<int>();
        var groupNames = groupIds
            .Select(id => GroupName(doc, id))
            .Cast<object>()
            .ToList();
        var isBlockInstance = obj is InstanceObject || geometry?.ObjectType == ObjectType.InstanceReference;
        var definitionName = string.Empty;
        if (obj is InstanceObject instanceObject)
        {
            definitionName = instanceObject.InstanceDefinition?.Name ?? string.Empty;
        }

        var full = new Dictionary<string, object>
        {
            ["object_id"] = obj.Id.ToString(),
            ["type"] = geometry?.ObjectType.ToString() ?? "Unknown",
            ["name"] = (attrs.Name ?? string.Empty).Trim(),
            ["layer"] = LayerName(doc, attrs),
            ["group_ids"] = groupIds.Select(id => id.ToString(CultureInfo.InvariantCulture)).Cast<object>().ToList(),
            ["group_names"] = groupNames,
            ["user_text"] = ReadUserText(attrs).ToDictionary(k => k.Key, v => (object)v.Value),
            ["material"] = ReadMaterial(doc, attrs),
            ["bbox"] = BboxMinMaxOnly(bbox),
            ["block_info"] = new Dictionary<string, object>
            {
                ["is_block_instance"] = isBlockInstance,
                ["definition_name"] = definitionName,
                ["instance_id"] = isBlockInstance ? obj.Id.ToString() : string.Empty
            },
            ["raw_geometry_summary"] = BuildRawGeometrySummaryLight(geometry, bbox)
        };

        // Promote the geometric scalars from raw_geometry_summary to top-level row
        // keys so a caller asking fields:["volume","obb_longest","longest_edge"] gets
        // them. Without this, ProjectRow looks for a flat "volume" key that does not
        // exist (the value is nested), and silently drops it — the reason fields-based
        // geometry queries returned null. Agnostic: just re-exposing computed facts.
        if (full["raw_geometry_summary"] is Dictionary<string, object> rgs)
        {
            foreach (var scalarKey in new[]
            {
                "volume", "area", "length", "face_count", "edge_count", "is_closed",
                "obb_dimensions", "obb_longest", "obb_mid", "obb_shortest", "longest_edge"
            })
            {
                if (rgs.TryGetValue(scalarKey, out var val) && !full.ContainsKey(scalarKey))
                {
                    full[scalarKey] = val;
                }
            }
        }

        if (fields is null)
        {
            return ProjectRow(full, new HashSet<string>(new[]
            {
                "object_id", "type", "name", "layer", "bbox"
            }, StringComparer.OrdinalIgnoreCase));
        }
        return ProjectRow(full, fields);
    }

    private static Dictionary<string, object> ProjectRow(Dictionary<string, object> full, HashSet<string> fields)
    {
        var outMap = new Dictionary<string, object>();
        foreach (var kv in full)
        {
            if (fields.Contains(kv.Key))
            {
                outMap[kv.Key] = kv.Value;
            }
        }
        return outMap;
    }

    private static Dictionary<string, object> BuildRawGeometrySummaryLight(GeometryBase? geometry, BoundingBox bbox)
    {
        var faceCount = 0;
        var edgeCount = 0;
        bool? isClosed = null;
        if (geometry is Brep brep)
        {
            faceCount = brep.Faces.Count;
            edgeCount = brep.Edges.Count;
            isClosed = brep.IsSolid;
        }
        else if (geometry is Mesh mesh)
        {
            faceCount = mesh.Faces.Count;
            edgeCount = mesh.TopologyEdges.Count;
            isClosed = mesh.IsClosed;
        }
        else if (geometry is Curve curve)
        {
            edgeCount = 1;
            isClosed = curve.IsClosed;
        }

        // The light summary previously omitted the geometric scalars, so a query
        // asking fields:["volume"] got null even though the value exists. Compute
        // them here too so the query path matches inspect_object. These are cheap
        // mass properties; the heavy face_areas/normals/sample_points stay out.
        double? lightLength = null;
        if (geometry is Curve c2)
        {
            try
            {
                var len = c2.GetLength();
                if (len > 0 && !double.IsNaN(len) && !double.IsInfinity(len)) lightLength = len;
            }
            catch { lightLength = null; }
        }
        var volume = ComputeVolume(geometry);
        var area = ComputeArea(geometry);
        var obb = ComputeObbDimensions(geometry, bbox);
        var longestEdge = ComputeLongestEdge(geometry);

        var map = new Dictionary<string, object>
        {
            ["bbox"] = BboxToSummaryDict(bbox),
            ["face_count"] = faceCount,
            ["edge_count"] = edgeCount,
            ["is_closed"] = isClosed.HasValue ? (object)isClosed.Value : null!,
            ["volume"] = volume.HasValue ? (object)volume.Value : null!,
            ["area"] = area.HasValue ? (object)area.Value : null!,
            ["length"] = lightLength.HasValue ? (object)lightLength.Value : null!,
            ["source"] = "rhino_bridge"
        };
        if (obb is not null)
        {
            map["obb_dimensions"] = obb.Cast<object>().ToList();
            map["obb_longest"] = obb[0];
            map["obb_mid"] = obb[1];
            map["obb_shortest"] = obb[2];
        }
        if (longestEdge.HasValue)
        {
            map["longest_edge"] = longestEdge.Value;
        }
        return map;
    }

    private static Dictionary<string, object> BuildLiveObjectBasic(RhinoDoc doc, RhinoObject obj, string userTextMode)
    {
        var attrs = obj.Attributes;
        var geometry = obj.Geometry;
        var bbox = GetValidBbox(geometry);
        var groupIds = attrs.GetGroupList() ?? Array.Empty<int>();
        var groupNames = groupIds
            .Select(id => GroupName(doc, id))
            .Cast<object>()
            .ToList();
        var isBlockInstance = obj is InstanceObject || geometry?.ObjectType == ObjectType.InstanceReference;
        var definitionName = string.Empty;
        if (obj is InstanceObject instanceObject)
        {
            definitionName = instanceObject.InstanceDefinition?.Name ?? string.Empty;
        }

        var map = new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["api"] = "v1_live",
            ["object_id"] = obj.Id.ToString(),
            ["type"] = geometry?.ObjectType.ToString() ?? "Unknown",
            ["name"] = (attrs.Name ?? string.Empty).Trim(),
            ["layer"] = LayerName(doc, attrs),
            ["group_ids"] = groupIds.Select(id => id.ToString(CultureInfo.InvariantCulture)).Cast<object>().ToList(),
            ["group_names"] = groupNames,
            ["material"] = ReadMaterial(doc, attrs),
            ["transform"] = ReadTransform(obj),
            ["block_info"] = new Dictionary<string, object>
            {
                ["is_block_instance"] = isBlockInstance,
                ["definition_name"] = definitionName,
                ["instance_id"] = isBlockInstance ? obj.Id.ToString() : string.Empty
            },
            ["raw_geometry_summary"] = BuildRawGeometrySummaryLight(geometry, bbox)
        };
        ApplyUserTextModeToMap(map, attrs, userTextMode);
        return map;
    }

    private static Dictionary<string, string> ReadUserText(ObjectAttributes attrs)
    {
        var outMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        NameValueCollection? bag = null;
        try
        {
            bag = attrs.GetUserStrings();
        }
        catch
        {
            bag = null;
        }
        if (bag is null)
        {
            return outMap;
        }
        foreach (var key in bag.AllKeys.Where(k => !string.IsNullOrWhiteSpace(k)))
        {
            outMap[key!] = bag[key] ?? string.Empty;
        }
        return outMap;
    }
}
