using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Rhino;
using Rhino.DocObjects;

namespace RhinoPrefabGeometryPlugin.Services;

public class FamilyService
{
    public Dictionary<string, object> ListNamedFamilies(RhinoDoc doc, IReadOnlyList<string>? prefixes = null)
    {
        var prefixFilter = new HashSet<string>(
            (prefixes ?? Array.Empty<string>())
                .Where(p => !string.IsNullOrWhiteSpace(p))
                .Select(p => p.Trim().ToUpperInvariant())
        );

        var families = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var familyPrefix = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var variants = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);

        foreach (var rhinoObject in doc.Objects)
        {
            var attrs = rhinoObject.Attributes;
            var familyName = ReadFamilyName(attrs);
            if (string.IsNullOrWhiteSpace(familyName))
            {
                continue;
            }

            var prefix = DetectPrefix(familyName);
            if (prefixFilter.Count > 0 && !prefixFilter.Contains(prefix))
            {
                continue;
            }

            families[familyName] = families.TryGetValue(familyName, out var count) ? count + 1 : 1;
            familyPrefix[familyName] = prefix;
            if (!variants.TryGetValue(familyName, out var values))
            {
                values = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                variants[familyName] = values;
            }
            var variant = DetectVariant(familyName);
            if (!string.IsNullOrWhiteSpace(variant))
            {
                values.Add(variant);
            }
        }

        var entries = families
            .OrderByDescending(item => item.Value)
            .Select(item => new Dictionary<string, object>
            {
                ["name"] = item.Key,
                ["count"] = item.Value,
                ["prefix"] = familyPrefix.TryGetValue(item.Key, out var prefix) ? prefix : string.Empty,
                ["variants"] = variants.TryGetValue(item.Key, out var values)
                    ? values.OrderBy(v => v).ToList()
                    : new List<string>()
            })
            .Cast<object>()
            .ToList();

        return new Dictionary<string, object>
        {
            ["families"] = entries
        };
    }

    public Dictionary<string, object> SummarizeFamily(RhinoDoc doc, string name)
    {
        var groups = GroupedObjectsByFamily(doc, name);
        var allObjects = groups.Values.SelectMany(v => v).ToList();
        var layers = allObjects.Select(o => LayerName(doc, o.Attributes)).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(v => v).ToList();
        var materials = allObjects
            .Select(o => MaterialName(doc, o.Attributes))
            .Where(m => !string.IsNullOrWhiteSpace(m) && !string.Equals(m, "Unassigned", StringComparison.OrdinalIgnoreCase))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(v => v)
            .ToList();
        var typeCounts = allObjects
            .GroupBy(o => o.Geometry?.ObjectType.ToString() ?? "Unknown", StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.Count(), StringComparer.OrdinalIgnoreCase);
        var outliers = DetectOutlierGroups(groups);

        return new Dictionary<string, object>
        {
            ["name"] = name,
            ["groups"] = groups.Keys.OrderBy(k => k).Cast<object>().ToList(),
            ["layers"] = layers.Cast<object>().ToList(),
            ["materials"] = materials.Cast<object>().ToList(),
            ["outliers"] = outliers.Cast<object>().ToList(),
            ["object_type_counts"] = typeCounts.ToDictionary(k => k.Key, v => (object)v.Value),
            ["total_objects"] = allObjects.Count
        };
    }

    public Dictionary<string, object> GetFamilyInstances(RhinoDoc doc, string name)
    {
        var groups = GroupedObjectsByFamily(doc, name);
        var instances = groups
            .OrderBy(entry => entry.Key)
            .Select(entry =>
            {
                var role = DetectRole(entry.Value, doc);
                var layers = entry.Value
                    .Select(o => LayerName(doc, o.Attributes))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .OrderBy(v => v)
                    .Cast<object>()
                    .ToList();
                return new Dictionary<string, object>
                {
                    ["name"] = name,
                    ["group_id"] = entry.Key,
                    ["object_count"] = entry.Value.Count,
                    ["layers"] = layers,
                    ["role"] = role.role,
                    ["flags"] = role.flags.Cast<object>().ToList()
                };
            })
            .Cast<object>()
            .ToList();
        return new Dictionary<string, object>
        {
            ["name"] = name,
            ["instances"] = instances
        };
    }

    public bool TryGetFamilyGroupObjects(RhinoDoc doc, string familyName, string groupId, out List<RhinoObject> objects)
    {
        var groups = GroupedObjectsByFamily(doc, familyName);
        if (groups.TryGetValue(groupId, out var found))
        {
            objects = found;
            return true;
        }
        objects = new List<RhinoObject>();
        return false;
    }

    private static Dictionary<string, List<RhinoObject>> GroupedObjectsByFamily(RhinoDoc doc, string familyName)
    {
        var result = new Dictionary<string, List<RhinoObject>>(StringComparer.OrdinalIgnoreCase);
        foreach (var rhinoObject in doc.Objects)
        {
            var attrs = rhinoObject.Attributes;
            var currentFamily = ReadFamilyName(attrs);
            if (!string.Equals(currentFamily, familyName, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var groupList = attrs.GetGroupList();
            if (groupList is null || groupList.Length == 0)
            {
                var synthetic = $"ungrouped:{rhinoObject.Id}";
                AddToBucket(result, synthetic, rhinoObject);
                continue;
            }

            foreach (var groupId in groupList)
            {
                AddToBucket(result, groupId.ToString(), rhinoObject);
            }
        }
        return result;
    }

    private static void AddToBucket(Dictionary<string, List<RhinoObject>> buckets, string key, RhinoObject obj)
    {
        if (!buckets.TryGetValue(key, out var list))
        {
            list = new List<RhinoObject>();
            buckets[key] = list;
        }
        list.Add(obj);
    }

    private static (string role, List<string> flags) DetectRole(IReadOnlyList<RhinoObject> objects, RhinoDoc doc)
    {
        var flags = new List<string>();
        if (objects.Count == 0)
        {
            return ("partial", new List<string> { "empty_group" });
        }

        var names = string.Join(" ", objects.Select(o => o.Attributes.Name ?? string.Empty)).ToLowerInvariant();
        var layers = string.Join(" ", objects.Select(o => LayerName(doc, o.Attributes))).ToLowerInvariant();
        var text = $"{names} {layers}";
        var role = "partial";
        if (ContainsAny(text, "truss", "cercha", "beam", "viga", "struct"))
        {
            role = "structural";
        }
        else if (ContainsAny(text, "osb", "cladding", "panel", "revest"))
        {
            role = "cladding";
        }

        if (objects.Count <= 2)
        {
            flags.Add("low_object_count");
        }
        var geometryTypes = objects.Select(o => o.Geometry?.ObjectType.ToString() ?? "Unknown").Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        if (geometryTypes.Count == 1)
        {
            flags.Add("single_geometry_type");
        }
        if (objects.Any(o => (o.Attributes.Name ?? string.Empty).ToLowerInvariant().Contains("dup")))
        {
            role = "duplicate_candidate";
        }
        return (role, flags);
    }

    private static bool ContainsAny(string source, params string[] tokens)
    {
        return tokens.Any(source.Contains);
    }

    private static List<string> DetectOutlierGroups(Dictionary<string, List<RhinoObject>> groups)
    {
        if (groups.Count <= 1)
        {
            return new List<string>();
        }
        var counts = groups.Values.Select(v => (double)v.Count).ToList();
        var mean = counts.Average();
        var variance = counts.Select(c => (c - mean) * (c - mean)).Average();
        var std = Math.Sqrt(variance);
        if (std <= 1e-9)
        {
            return new List<string>();
        }
        return groups
            .Where(entry => Math.Abs((entry.Value.Count - mean) / std) >= 2.0)
            .Select(entry => entry.Key)
            .OrderBy(v => v)
            .ToList();
    }

    private static string LayerName(RhinoDoc doc, ObjectAttributes attrs)
    {
        return doc.Layers[attrs.LayerIndex]?.FullPath ?? "Unassigned";
    }

    private static string MaterialName(RhinoDoc doc, ObjectAttributes attrs)
    {
        if (attrs.MaterialIndex >= 0 && attrs.MaterialIndex < doc.Materials.Count)
        {
            return doc.Materials[attrs.MaterialIndex]?.Name ?? "Unassigned";
        }
        return "Unassigned";
    }

    private static string ReadFamilyName(ObjectAttributes attrs)
    {
        var fromUserText = attrs.GetUserString("Nombre")
            ?? attrs.GetUserString("name")
            ?? attrs.GetUserString("Name")
            ?? attrs.GetUserString("Family")
            ?? attrs.GetUserString("family");
        if (!string.IsNullOrWhiteSpace(fromUserText))
        {
            return fromUserText.Trim();
        }
        return attrs.Name?.Trim() ?? string.Empty;
    }

    private static string DetectPrefix(string value)
    {
        var token = (value ?? string.Empty).Trim();
        var match = Regex.Match(token, "^([A-Za-z]+)");
        if (match.Success)
        {
            return match.Groups[1].Value.ToUpperInvariant();
        }
        var split = token.Split(new[] { '_', '-', ' ' }, StringSplitOptions.RemoveEmptyEntries);
        return split.Length > 0 ? split[0].ToUpperInvariant() : string.Empty;
    }

    private static string DetectVariant(string value)
    {
        var token = (value ?? string.Empty).Trim();
        var match = Regex.Match(token, "([A-Za-z])$");
        return match.Success ? match.Groups[1].Value.ToUpperInvariant() : string.Empty;
    }
}

