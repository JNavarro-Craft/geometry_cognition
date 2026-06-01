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

    public Dictionary<string, object> LiveGetDefinitionObjects(RhinoDoc doc, string definitionName)
    {
        // Return the objects that COMPOSE a block definition (1.3a: raw content, no
        // instance transform applied). This is what lets a caller read attributes/
        // text/geometry that live INSIDE a block, previously unreachable.
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

        var objects = new List<object>();
        foreach (var mid in idef.GetObjectIds() ?? Array.Empty<Guid>())
        {
            var mobj = doc.Objects.FindId(mid);
            if (mobj is not null)
            {
                objects.Add(ExtractObject(doc, mobj));
            }
        }

        int instanceCount;
        try { instanceCount = idef.GetReferences(0)?.Length ?? 0; }
        catch { instanceCount = 0; }

        return new Dictionary<string, object>
        {
            ["source"] = "rhino_bridge",
            ["api"] = "v1_live",
            ["definition_name"] = idef.Name ?? string.Empty,
            ["definition_id"] = idef.Id.ToString(),
            ["instance_count"] = instanceCount,
            ["object_count"] = objects.Count,
            ["transform_applied"] = false,
            ["objects"] = objects,
        };
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
        else if (geometry is Curve curve)
        {
            edgeCount = 1;
            isClosed = curve.IsClosed;
        }

        volume = ComputeVolume(geometry);
        area = ComputeArea(geometry);

        var corners = bbox.IsValid
            ? bbox.GetCorners().Select(p => (object)new List<double> { p.X, p.Y, p.Z }).ToList()
            : new List<object>();
        var samplePoints = BuildSamplePoints(bbox, 6);

        return new Dictionary<string, object>
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
            ["source"] = "rhino_bridge"
        };
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

        return new Dictionary<string, object>
        {
            ["bbox"] = BboxToSummaryDict(bbox),
            ["face_count"] = faceCount,
            ["edge_count"] = edgeCount,
            ["is_closed"] = isClosed.HasValue ? (object)isClosed.Value : null!,
            ["source"] = "rhino_bridge"
        };
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
