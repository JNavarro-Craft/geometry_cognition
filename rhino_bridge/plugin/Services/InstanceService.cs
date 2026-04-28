using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Globalization;
using System.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoPrefabGeometryPlugin.Services;

public class InstanceService
{
    public Dictionary<string, object> ListGroups(RhinoDoc doc)
    {
        var grouped = BuildGroupBuckets(doc);
        var ungroupedCount = doc.Objects.Count(o => !HasGroups(o.Attributes));
        var groups = grouped
            .OrderBy(entry => entry.Key)
            .Select(entry => BuildGroupSummary(doc, entry.Key, entry.Value))
            .Cast<object>()
            .ToList();

        var warnings = new List<string>();
        if (ungroupedCount > 0)
        {
            warnings.Add($"{ungroupedCount} objects are not assigned to any Group.");
        }

        return new Dictionary<string, object>
        {
            ["groups"] = groups,
            ["ungrouped_object_count"] = ungroupedCount,
            ["warnings"] = warnings.Cast<object>().ToList()
        };
    }

    public Dictionary<string, object> InspectMetadataCoverage(RhinoDoc doc)
    {
        var total = doc.Objects.Count;
        var keyDistribution = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var objectsWithMetadata = 0;
        var objectsWithoutMetadata = new List<string>();

        foreach (var obj in doc.Objects)
        {
            var userText = ReadUserText(obj.Attributes);
            if (userText.Count == 0)
            {
                if (objectsWithoutMetadata.Count < 25)
                {
                    objectsWithoutMetadata.Add(obj.Id.ToString());
                }
                continue;
            }
            objectsWithMetadata += 1;
            foreach (var key in userText.Keys)
            {
                keyDistribution[key] = keyDistribution.TryGetValue(key, out var count) ? count + 1 : 1;
            }
        }

        var inconsistencies = new List<string>();
        var caseBuckets = keyDistribution.Keys
            .GroupBy(k => k.ToLowerInvariant())
            .Where(g => g.Select(x => x).Distinct().Count() > 1);
        foreach (var bucket in caseBuckets)
        {
            inconsistencies.Add($"Key casing mismatch: {string.Join(", ", bucket.OrderBy(v => v))}");
        }
        if (keyDistribution.Count == 0)
        {
            inconsistencies.Add("No UserText keys detected.");
        }

        var coverage = total > 0 ? (double)objectsWithMetadata / total : 0.0;
        return new Dictionary<string, object>
        {
            ["total_objects"] = total,
            ["objects_with_usertext"] = objectsWithMetadata,
            ["coverage_ratio"] = Math.Round(coverage, 4),
            ["coverage_percent"] = Math.Round(coverage * 100.0, 2),
            ["keys_detected"] = keyDistribution.Keys
                .OrderBy(k => k)
                .Select(k => new Dictionary<string, object>
                {
                    ["key"] = k,
                    ["source"] = "usertext"
                })
                .Cast<object>()
                .ToList(),
            ["keys_detected_legacy"] = keyDistribution.Keys.OrderBy(k => k).Cast<object>().ToList(),
            ["key_distribution"] = keyDistribution
                .OrderByDescending(item => item.Value)
                .Select(item => new Dictionary<string, object>
                {
                    ["key"] = item.Key,
                    ["count"] = item.Value,
                    ["source"] = "usertext"
                })
                .Cast<object>()
                .ToList(),
            ["objects_without_metadata"] = new Dictionary<string, object>
            {
                ["count"] = total - objectsWithMetadata,
                ["sample_object_ids"] = objectsWithoutMetadata.Cast<object>().ToList()
            },
            ["inconsistencies"] = inconsistencies.Cast<object>().ToList()
        };
    }

    public Dictionary<string, object> ListUngroupedObjects(RhinoDoc doc)
    {
        var ungrouped = doc.Objects
            .Where(o => !HasGroups(o.Attributes))
            .ToList();
        var typeDistribution = ungrouped
            .GroupBy(o => o.Geometry?.ObjectType.ToString() ?? "Unknown", StringComparer.OrdinalIgnoreCase)
            .OrderByDescending(g => g.Count())
            .Select(g => new Dictionary<string, object>
            {
                ["type"] = g.Key,
                ["count"] = g.Count()
            })
            .Cast<object>()
            .ToList();
        var layerDistribution = ungrouped
            .GroupBy(o => LayerName(doc, o.Attributes), StringComparer.OrdinalIgnoreCase)
            .OrderByDescending(g => g.Count())
            .Select(g => new Dictionary<string, object>
            {
                ["layer"] = g.Key,
                ["count"] = g.Count()
            })
            .Cast<object>()
            .ToList();

        var namedCount = 0;
        var objectsWithUserTextCount = 0;
        var samples = new List<object>();
        foreach (var obj in ungrouped.Take(12))
        {
            var name = ReadFamilyNameWithSource(obj.Attributes);
            var userText = ReadUserText(obj.Attributes);
            if (!string.IsNullOrWhiteSpace(name.value))
            {
                namedCount += 1;
            }
            if (userText.Count > 0)
            {
                objectsWithUserTextCount += 1;
            }
            samples.Add(new Dictionary<string, object>
            {
                ["object_id"] = obj.Id.ToString(),
                ["type"] = obj.Geometry?.ObjectType.ToString() ?? "Unknown",
                ["layer"] = LayerName(doc, obj.Attributes),
                ["name"] = name.value,
                ["name_source"] = name.source,
                ["has_usertext"] = userText.Count > 0
            });
        }

        // Count named/usertext in full ungrouped set for consistent summary.
        foreach (var obj in ungrouped.Skip(12))
        {
            var name = ReadFamilyNameWithSource(obj.Attributes);
            if (!string.IsNullOrWhiteSpace(name.value))
            {
                namedCount += 1;
            }
            if (ReadUserText(obj.Attributes).Count > 0)
            {
                objectsWithUserTextCount += 1;
            }
        }

        return new Dictionary<string, object>
        {
            ["count"] = ungrouped.Count,
            ["type_distribution"] = typeDistribution,
            ["layer_distribution"] = layerDistribution,
            ["named_count"] = namedCount,
            ["objects_with_usertext_count"] = objectsWithUserTextCount,
            ["sample_objects"] = samples
        };
    }

    public Dictionary<string, object> GetObjectSummary(RhinoDoc doc, string objectId)
    {
        var obj = ResolveObjectById(doc, objectId);
        var nameInfo = ReadFamilyNameWithSource(obj.Attributes);
        var userText = ReadUserText(obj.Attributes);
        var summary = ToGeometryObservation(doc, obj);
        var warnings = new List<string>();
        if (!(summary.TryGetValue("bbox_dims_approx", out _)))
        {
            warnings.Add("Bounding box unavailable; centroid and dimensions fallback applied.");
        }

        var payload = new Dictionary<string, object>
        {
            ["object_id"] = obj.Id.ToString(),
            ["type"] = summary["type"],
            ["layer"] = summary["layer"],
            ["name_info"] = new Dictionary<string, object>
            {
                ["value"] = nameInfo.value,
                ["source"] = nameInfo.source
            },
            ["metadata_summary"] = new Dictionary<string, object>
            {
                ["has_usertext"] = userText.Count > 0,
                ["key_count"] = userText.Count
            },
            ["centroid_world"] = summary["centroid_world"],
            ["bbox_dims_approx"] = summary["bbox_dims_approx"],
            ["warnings"] = warnings.Cast<object>().ToList()
        };
        if (summary.TryGetValue("length", out var curveLength))
        {
            payload["curve_length"] = curveLength;
        }
        if (summary.TryGetValue("edge_metrics", out var edgeMetrics))
        {
            payload["edge_metrics"] = edgeMetrics;
        }
        return payload;
    }

    public Dictionary<string, object> GetObjectNeighborhood(RhinoDoc doc, string objectId, string mode)
    {
        var normalizedMode = (mode ?? string.Empty).Trim().ToLowerInvariant();
        if (!string.Equals(normalizedMode, "spatial", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Unsupported mode. Only mode=spatial is currently available.");
        }

        var anchor = ResolveObjectById(doc, objectId);
        var anchorBbox = GetValidBbox(anchor);
        var anchorCentroid = anchorBbox.IsValid ? anchorBbox.Center : Point3d.Origin;
        var anchorDiag = anchorBbox.IsValid ? anchorBbox.Diagonal.Length : 0.0;
        var nearThreshold = Math.Max(doc.ModelAbsoluteTolerance * 50.0, Math.Max(anchorDiag * 1.5, 1.0));

        var neighbors = new List<Dictionary<string, object>>();
        foreach (var obj in doc.Objects)
        {
            if (obj.Id == anchor.Id)
            {
                continue;
            }

            var bbox = GetValidBbox(obj);
            var centroid = bbox.IsValid ? bbox.Center : Point3d.Origin;
            var distance = anchorCentroid.DistanceTo(centroid);
            var overlap = anchorBbox.IsValid && bbox.IsValid && BoundingBox.Intersection(anchorBbox, bbox).IsValid;
            var touching = anchorBbox.IsValid && bbox.IsValid && BboxGap(anchorBbox, bbox) <= doc.ModelAbsoluteTolerance * 4.0;
            var centroidNear = distance <= nearThreshold;
            if (!(overlap || touching || centroidNear))
            {
                continue;
            }

            var relationHints = new List<string>();
            if (overlap) relationHints.Add("bbox_overlap");
            if (centroidNear) relationHints.Add("centroid_near");
            if (touching) relationHints.Add("touching_candidate");
            var confidence = BuildNeighborhoodConfidence(overlap, centroidNear, touching, distance, nearThreshold);

            neighbors.Add(new Dictionary<string, object>
            {
                ["object_id"] = obj.Id.ToString(),
                ["type"] = obj.Geometry?.ObjectType.ToString() ?? "Unknown",
                ["layer"] = LayerName(doc, obj.Attributes),
                ["distance_hint"] = Math.Round(distance, 4),
                ["relation_hints"] = relationHints.Cast<object>().ToList(),
                ["confidence"] = confidence
            });
        }

        var ordered = neighbors
            .OrderByDescending(n => Convert.ToDouble(n["confidence"]))
            .ThenBy(n => Convert.ToDouble(n["distance_hint"]))
            .Take(24)
            .Cast<object>()
            .ToList();

        var warnings = new List<string>();
        if (ordered.Count == 0)
        {
            warnings.Add("No nearby objects detected with current spatial heuristics.");
        }

        return new Dictionary<string, object>
        {
            ["anchor_object_id"] = anchor.Id.ToString(),
            ["mode"] = "spatial",
            ["neighbors"] = ordered,
            ["warnings"] = warnings.Cast<object>().ToList()
        };
    }

    public Dictionary<string, object> GetInstanceGeometry(RhinoDoc doc, string instanceId)
    {
        var resolved = ResolveInstance(doc, instanceId);
        var objects = resolved.objects
            .Select(obj => ToGeometryObservation(doc, obj))
            .Cast<object>()
            .ToList();

        return new Dictionary<string, object>
        {
            ["instance_ref"] = new Dictionary<string, object>
            {
                ["instance_id"] = resolved.instanceId,
                ["source"] = resolved.source,
                ["family_name"] = resolved.familyName,
                ["family_name_source"] = resolved.familyNameSource,
                ["confidence"] = resolved.confidence
            },
            ["object_count"] = resolved.objects.Count,
            ["objects"] = objects,
            ["warnings"] = resolved.warnings.Cast<object>().ToList()
        };
    }

    public (string instanceId, string source, string familyName, string familyNameSource, double confidence, List<RhinoObject> objects, List<string> warnings) ResolveInstance(
        RhinoDoc doc,
        string instanceId
    )
    {
        var normalized = (instanceId ?? string.Empty).Trim();
        if (string.IsNullOrWhiteSpace(normalized))
        {
            throw new InvalidOperationException("instance_id is required.");
        }

        if (normalized.StartsWith("grp:", StringComparison.OrdinalIgnoreCase))
        {
            var groupToken = normalized.Substring(4);
            return ResolveGroup(doc, groupToken, normalized);
        }
        if (normalized.StartsWith("obj:", StringComparison.OrdinalIgnoreCase))
        {
            var objectToken = normalized.Substring(4);
            return ResolveObject(doc, objectToken, normalized);
        }
        if (normalized.StartsWith("cand:", StringComparison.OrdinalIgnoreCase))
        {
            throw new KeyNotFoundException("candidate instance ids require /detect-composite-instances (not implemented).");
        }

        if (int.TryParse(normalized, NumberStyles.Integer, CultureInfo.InvariantCulture, out _))
        {
            return ResolveGroup(doc, normalized, $"grp:{normalized}");
        }
        return ResolveObject(doc, normalized, $"obj:{normalized}");
    }

    private static (string instanceId, string source, string familyName, string familyNameSource, double confidence, List<RhinoObject> objects, List<string> warnings) ResolveGroup(
        RhinoDoc doc,
        string groupToken,
        string normalizedId
    )
    {
        if (!int.TryParse(groupToken, NumberStyles.Integer, CultureInfo.InvariantCulture, out var groupId))
        {
            throw new InvalidOperationException("Group instance_id must be numeric, for example grp:12.");
        }

        var objects = doc.Objects
            .Where(obj =>
            {
                var groups = obj.Attributes.GetGroupList();
                return groups is not null && groups.Contains(groupId);
            })
            .ToList();
        if (objects.Count == 0)
        {
            throw new KeyNotFoundException($"Group '{groupId}' was not found.");
        }

        var family = InferFamilyName(objects);
        return (
            normalizedId,
            "group",
            family.familyName,
            family.familyNameSource,
            0.98,
            objects,
            new List<string>()
        );
    }

    private static (string instanceId, string source, string familyName, string familyNameSource, double confidence, List<RhinoObject> objects, List<string> warnings) ResolveObject(
        RhinoDoc doc,
        string objectToken,
        string normalizedId
    )
    {
        if (!Guid.TryParse(objectToken, out var objectId))
        {
            throw new InvalidOperationException("Object instance_id must be a valid guid, for example obj:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.");
        }
        var obj = doc.Objects.FindId(objectId);
        if (obj is null)
        {
            throw new KeyNotFoundException($"Object '{objectToken}' was not found.");
        }

        var family = ReadFamilyNameWithSource(obj.Attributes);
        var warnings = new List<string> { "Single-object instance inferred from object id." };
        return (
            normalizedId,
            "geometry",
            family.value,
            family.source,
            0.55,
            new List<RhinoObject> { obj },
            warnings
        );
    }

    private static Dictionary<string, List<RhinoObject>> BuildGroupBuckets(RhinoDoc doc)
    {
        var buckets = new Dictionary<string, List<RhinoObject>>(StringComparer.OrdinalIgnoreCase);
        foreach (var obj in doc.Objects)
        {
            var groups = obj.Attributes.GetGroupList();
            if (groups is null || groups.Length == 0)
            {
                continue;
            }
            foreach (var groupId in groups)
            {
                var key = groupId.ToString(CultureInfo.InvariantCulture);
                if (!buckets.TryGetValue(key, out var list))
                {
                    list = new List<RhinoObject>();
                    buckets[key] = list;
                }
                list.Add(obj);
            }
        }
        return buckets;
    }

    private static Dictionary<string, object> BuildGroupSummary(RhinoDoc doc, string groupId, IReadOnlyList<RhinoObject> objects)
    {
        var layers = objects
            .Select(o => LayerName(doc, o.Attributes))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(v => v)
            .Cast<object>()
            .ToList();
        var family = InferFamilyName(objects);
        var nameHints = BuildNameHintsWithSource(objects);
        var nameHintsLegacy = nameHints
            .Select(item => item["value"]?.ToString() ?? string.Empty)
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Cast<object>()
            .ToList();
        var aggregateBounds = ComputeAggregateBounds(objects);
        var metadata = ComputeMetadataPresence(objects);
        var warnings = new List<string>();
        if (metadata.coverage < 0.35)
        {
            warnings.Add("Low metadata coverage in this group.");
        }
        return new Dictionary<string, object>
        {
            ["group_id"] = groupId,
            ["instance_ref"] = new Dictionary<string, object>
            {
                ["instance_id"] = $"grp:{groupId}",
                ["source"] = "group",
                ["family_name"] = family.familyName,
                ["family_name_source"] = family.familyNameSource,
                ["confidence"] = 0.98
            },
            ["instance_id"] = $"grp:{groupId}",
            ["object_count"] = objects.Count,
            ["layers"] = layers,
            ["name_hints"] = nameHints.Cast<object>().ToList(),
            ["name_hints_legacy"] = nameHintsLegacy,
            ["bounding_summary"] = aggregateBounds,
            ["metadata_presence"] = metadata.payload,
            ["warnings"] = warnings.Cast<object>().ToList()
        };
    }

    private static Dictionary<string, object> ComputeAggregateBounds(IReadOnlyList<RhinoObject> objects)
    {
        var min = new Point3d(double.PositiveInfinity, double.PositiveInfinity, double.PositiveInfinity);
        var max = new Point3d(double.NegativeInfinity, double.NegativeInfinity, double.NegativeInfinity);
        foreach (var obj in objects)
        {
            var bbox = obj.Geometry?.GetBoundingBox(true) ?? BoundingBox.Unset;
            if (!bbox.IsValid)
            {
                continue;
            }
            min.X = Math.Min(min.X, bbox.Min.X);
            min.Y = Math.Min(min.Y, bbox.Min.Y);
            min.Z = Math.Min(min.Z, bbox.Min.Z);
            max.X = Math.Max(max.X, bbox.Max.X);
            max.Y = Math.Max(max.Y, bbox.Max.Y);
            max.Z = Math.Max(max.Z, bbox.Max.Z);
        }

        if (!min.IsValid || !max.IsValid || double.IsInfinity(min.X) || double.IsInfinity(max.X))
        {
            return new Dictionary<string, object>
            {
                ["valid"] = false
            };
        }
        var size = max - min;
        return new Dictionary<string, object>
        {
            ["valid"] = true,
            ["min"] = new List<double> { min.X, min.Y, min.Z },
            ["max"] = new List<double> { max.X, max.Y, max.Z },
            ["size"] = new List<double> { size.X, size.Y, size.Z },
            ["diag"] = size.Length
        };
    }

    private static (double coverage, Dictionary<string, object> payload) ComputeMetadataPresence(IReadOnlyList<RhinoObject> objects)
    {
        var withMetadata = 0;
        var keys = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var obj in objects)
        {
            var data = ReadUserText(obj.Attributes);
            if (data.Count == 0)
            {
                continue;
            }
            withMetadata += 1;
            foreach (var key in data.Keys)
            {
                keys[key] = keys.TryGetValue(key, out var count) ? count + 1 : 1;
            }
        }
        var coverage = objects.Count > 0 ? (double)withMetadata / objects.Count : 0.0;
        var payload = new Dictionary<string, object>
        {
            ["objects_with_usertext"] = withMetadata,
            ["coverage_ratio"] = Math.Round(coverage, 4),
            ["keys"] = keys.OrderByDescending(item => item.Value)
                .Take(8)
                .Select(item => new Dictionary<string, object>
                {
                    ["key"] = item.Key,
                    ["count"] = item.Value,
                    ["source"] = "usertext"
                })
                .Cast<object>()
                .ToList()
        };
        return (coverage, payload);
    }

    private static Dictionary<string, object> ToGeometryObservation(RhinoDoc doc, RhinoObject obj)
    {
        var geometry = obj.Geometry;
        var bbox = geometry?.GetBoundingBox(true) ?? BoundingBox.Unset;
        if (!bbox.IsValid && geometry is not null)
        {
            bbox = geometry.GetBoundingBox(false);
        }
        var centroid = bbox.IsValid ? bbox.Center : Point3d.Origin;
        var size = bbox.IsValid ? bbox.Max - bbox.Min : Vector3d.Zero;

        var payload = new Dictionary<string, object>
        {
            ["object_id"] = obj.Id.ToString(),
            ["type"] = geometry?.ObjectType.ToString() ?? "Unknown",
            ["layer"] = LayerName(doc, obj.Attributes),
            ["name"] = (obj.Attributes.Name ?? string.Empty).Trim(),
            ["centroid_world"] = new List<double> { centroid.X, centroid.Y, centroid.Z },
            ["bbox_dims_approx"] = new Dictionary<string, object>
            {
                ["axes"] = "world_xyz",
                ["values"] = new List<double> { size.X, size.Y, size.Z }
            },
            ["dims_approx"] = new List<double> { size.X, size.Y, size.Z }
        };

        if (geometry is Curve curve)
        {
            payload["length"] = curve.GetLength();
        }
        if (geometry is Brep brep)
        {
            var lengths = brep.Edges.Select(e => e.GetLength()).Where(v => v > 0).ToList();
            payload["edge_metrics"] = new Dictionary<string, object>
            {
                ["edge_count"] = brep.Edges.Count,
                ["min_length"] = lengths.Count > 0 ? lengths.Min() : 0.0,
                ["max_length"] = lengths.Count > 0 ? lengths.Max() : 0.0,
                ["avg_length"] = lengths.Count > 0 ? lengths.Average() : 0.0
            };
        }
        return payload;
    }

    private static RhinoObject ResolveObjectById(RhinoDoc doc, string objectId)
    {
        var token = (objectId ?? string.Empty).Trim();
        if (token.StartsWith("obj:", StringComparison.OrdinalIgnoreCase))
        {
            token = token.Substring(4);
        }
        if (!Guid.TryParse(token, out var guid))
        {
            throw new InvalidOperationException("object_id must be a valid guid.");
        }
        var obj = doc.Objects.FindId(guid);
        if (obj is null)
        {
            throw new KeyNotFoundException($"Object '{token}' was not found.");
        }
        return obj;
    }

    private static BoundingBox GetValidBbox(RhinoObject obj)
    {
        var bbox = obj.Geometry?.GetBoundingBox(true) ?? BoundingBox.Unset;
        if (!bbox.IsValid && obj.Geometry is not null)
        {
            bbox = obj.Geometry.GetBoundingBox(false);
        }
        return bbox;
    }

    private static double BuildNeighborhoodConfidence(bool overlap, bool centroidNear, bool touching, double distance, double nearThreshold)
    {
        var score = 0.0;
        if (overlap) score += 0.45;
        if (touching) score += 0.35;
        if (centroidNear) score += 0.2;
        var normalizedDistance = nearThreshold > 1e-9 ? Math.Min(1.0, distance / nearThreshold) : 1.0;
        score -= normalizedDistance * 0.15;
        return Math.Round(Math.Max(0.05, Math.Min(0.99, score)), 4);
    }

    private static double BboxGap(BoundingBox a, BoundingBox b)
    {
        var dx = Math.Max(0.0, Math.Max(a.Min.X - b.Max.X, b.Min.X - a.Max.X));
        var dy = Math.Max(0.0, Math.Max(a.Min.Y - b.Max.Y, b.Min.Y - a.Max.Y));
        var dz = Math.Max(0.0, Math.Max(a.Min.Z - b.Max.Z, b.Min.Z - a.Max.Z));
        return Math.Sqrt(dx * dx + dy * dy + dz * dz);
    }

    private static bool HasGroups(ObjectAttributes attrs)
    {
        var groups = attrs.GetGroupList();
        return groups is not null && groups.Length > 0;
    }

    private static string LayerName(RhinoDoc doc, ObjectAttributes attrs)
    {
        return doc.Layers[attrs.LayerIndex]?.FullPath ?? "Unassigned";
    }

    private static (string familyName, string familyNameSource) InferFamilyName(IReadOnlyList<RhinoObject> objects)
    {
        var counts = new Dictionary<(string value, string source), int>();
        foreach (var obj in objects)
        {
            var hint = ReadFamilyNameWithSource(obj.Attributes);
            if (string.IsNullOrWhiteSpace(hint.value))
            {
                continue;
            }
            var key = (hint.value, hint.source);
            counts[key] = counts.TryGetValue(key, out var count) ? count + 1 : 1;
        }
        if (counts.Count == 0)
        {
            return (string.Empty, "none");
        }
        var best = counts.OrderByDescending(item => item.Value).First();
        return (best.Key.value, best.Key.source);
    }

    private static string ReadFamilyName(ObjectAttributes attrs)
    {
        return ReadFamilyNameWithSource(attrs).value;
    }

    private static (string value, string source) ReadFamilyNameWithSource(ObjectAttributes attrs)
    {
        var fromName = attrs.GetUserString("Nombre")
            ?? attrs.GetUserString("name")
            ?? attrs.GetUserString("Name");
        if (!string.IsNullOrWhiteSpace(fromName))
        {
            return (fromName.Trim(), "usertext:name");
        }
        var fromFamily = attrs.GetUserString("Family")
            ?? attrs.GetUserString("family");
        if (!string.IsNullOrWhiteSpace(fromFamily))
        {
            return (fromFamily.Trim(), "usertext:family");
        }
        var fromObjectName = attrs.Name?.Trim() ?? string.Empty;
        if (!string.IsNullOrWhiteSpace(fromObjectName))
        {
            return (fromObjectName, "object_name");
        }
        return (string.Empty, "none");
    }

    private static List<Dictionary<string, object>> BuildNameHintsWithSource(IReadOnlyList<RhinoObject> objects)
    {
        var counts = new Dictionary<(string value, string source), int>();
        foreach (var obj in objects)
        {
            var hint = ReadFamilyNameWithSource(obj.Attributes);
            if (string.IsNullOrWhiteSpace(hint.value))
            {
                continue;
            }
            var key = (hint.value, hint.source);
            counts[key] = counts.TryGetValue(key, out var count) ? count + 1 : 1;
        }
        return counts
            .OrderByDescending(item => item.Value)
            .Take(5)
            .Select(item => new Dictionary<string, object>
            {
                ["value"] = item.Key.value,
                ["source"] = item.Key.source,
                ["count"] = item.Value
            })
            .ToList();
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
            var value = bag[key] ?? string.Empty;
            outMap[key!] = value;
        }
        return outMap;
    }
}

