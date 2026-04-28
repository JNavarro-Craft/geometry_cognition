using System.Collections.Generic;

namespace RhinoPrefabGeometryPlugin.Models;

public class ModelSummary
{
    public int TotalObjects { get; set; }
    public List<string> RelevantLayers { get; set; } = new();
    public Dictionary<string, Dictionary<string, int>> GeometryTypesByLayer { get; set; } = new();
    public List<Dictionary<string, object>> DetectedNames { get; set; } = new();
    public List<string> Warnings { get; set; } = new();
}

