using System;
using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.DocObjects;
using RhinoPrefabGeometryPlugin.Models;

namespace RhinoPrefabGeometryPlugin.Services;

public class SceneService
{
    public ModelSummary SummarizeModel(RhinoDoc doc)
    {
        var byLayer = new Dictionary<string, Dictionary<string, int>>(StringComparer.OrdinalIgnoreCase);
        var names = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var warnings = new List<string>();
        var instanceRefs = 0;
        var total = 0;

        foreach (var rhinoObject in doc.Objects)
        {
            total += 1;
            var attrs = rhinoObject.Attributes;
            var layerName = doc.Layers[attrs.LayerIndex]?.FullPath ?? "Unassigned";
            var typeName = rhinoObject.Geometry?.ObjectType.ToString() ?? "Unknown";
            if (!byLayer.TryGetValue(layerName, out var typeCounts))
            {
                typeCounts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
                byLayer[layerName] = typeCounts;
            }
            typeCounts[typeName] = typeCounts.TryGetValue(typeName, out var count) ? count + 1 : 1;

            var name = ReadFamilyName(attrs);
            if (!string.IsNullOrWhiteSpace(name))
            {
                names[name] = names.TryGetValue(name, out var value) ? value + 1 : 1;
            }

            if (rhinoObject is InstanceObject || rhinoObject.Geometry?.ObjectType == ObjectType.InstanceReference)
            {
                instanceRefs += 1;
            }
        }

        if (instanceRefs > 0)
        {
            warnings.Add($"{instanceRefs} instance references detected; expand if deeper metrics are needed.");
        }

        return new ModelSummary
        {
            TotalObjects = total,
            RelevantLayers = byLayer.Keys.OrderBy(k => k).ToList(),
            GeometryTypesByLayer = byLayer,
            DetectedNames = names
                .OrderByDescending(item => item.Value)
                .Select(item => new Dictionary<string, object>
                {
                    ["name"] = item.Key,
                    ["count"] = item.Value
                })
                .ToList(),
            Warnings = warnings
        };
    }

    private static string ReadFamilyName(ObjectAttributes attrs)
    {
        var fromUserText = attrs.GetUserString("Nombre")
            ?? attrs.GetUserString("name")
            ?? attrs.GetUserString("Name")
            ?? attrs.GetUserString("Family");
        if (!string.IsNullOrWhiteSpace(fromUserText))
        {
            return fromUserText.Trim();
        }
        return attrs.Name?.Trim() ?? string.Empty;
    }
}

