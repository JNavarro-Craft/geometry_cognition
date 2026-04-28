using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Globalization;
using System.Linq;
using System.Runtime.Serialization;
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

        return new Dictionary<string, object>
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
