using System;
using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace RhinoPrefabGeometryPlugin.Services;

public class FrameService
{
    public Dictionary<string, object> GetInstanceFrameCandidates(RhinoDoc doc, InstanceService instanceService, string instanceId)
    {
        var resolved = instanceService.ResolveInstance(doc, instanceId);
        var points = resolved.objects
            .Select(ReadCentroid)
            .ToList();
        var warnings = new List<string>(resolved.warnings);
        var candidates = EstimateFrameCandidates(points, warnings);
        var recommendation = SelectRecommendedFrame(candidates);
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
            ["candidates"] = candidates.Cast<object>().ToList(),
            ["recommended_frame_id"] = recommendation.frameId,
            ["recommendation_basis"] = recommendation.basis,
            ["warnings"] = warnings.Cast<object>().ToList()
        };
    }

    public Dictionary<string, object> GetLegacySingleFrame(RhinoDoc doc, InstanceService instanceService, string instanceId)
    {
        var payload = GetInstanceFrameCandidates(doc, instanceService, instanceId);
        var candidates = payload.TryGetValue("candidates", out var value) ? value as List<object> : null;
        Dictionary<string, object>? selected = null;
        if (candidates is not null && candidates.Count > 0)
        {
            selected = candidates
                .OfType<Dictionary<string, object>>()
                .OrderByDescending(item => item.TryGetValue("confidence", out var c) ? Convert.ToDouble(c) : 0.0)
                .FirstOrDefault();
        }
        if (selected is null)
        {
            throw new InvalidOperationException("No frame candidates available.");
        }
        selected["warnings"] = payload.TryGetValue("warnings", out var warnings) && warnings is List<object> list
            ? list
            : new List<object>();
        return selected;
    }

    private static List<Dictionary<string, object>> EstimateFrameCandidates(IReadOnlyList<Point3d> points, List<string> warnings)
    {
        var objectCount = points.Count;
        var symmetryRisk = EstimateSymmetryRisk(points);
        if (points.Count < 2)
        {
            warnings.Add("Insufficient points; default world frame fallback.");
            var origin = points.Count == 1 ? points[0] : Point3d.Origin;
            return new List<Dictionary<string, object>>
            {
                FrameCandidate(
                    "frame:fallback_world",
                    origin,
                    Vector3d.XAxis,
                    Vector3d.YAxis,
                    Vector3d.ZAxis,
                    "fallback_world",
                    0.2,
                    objectCount,
                    null,
                    symmetryRisk,
                    new List<string>()
                )
            };
        }

        var originPoint = Average(points);
        var candidates = new List<Dictionary<string, object>>();
        candidates.Add(FrameCandidate(
            "frame:world_xy",
            originPoint,
            Vector3d.XAxis,
            Vector3d.YAxis,
            Vector3d.ZAxis,
            "world_xy",
            0.25,
            objectCount,
            null,
            symmetryRisk,
            new List<string>()
        ));

        // Delicate geometry decision: infer longitudinal axis from farthest pair
        // to avoid assuming world alignment on prefab instances.
        var xAxis = AxisFromFarthestPair(points);
        var zAxis = NormalFromSmallestSpread(points);
        var localWarnings = new List<string>();
        if (Math.Abs(Vector3d.Multiply(xAxis, zAxis)) > 0.95)
        {
            zAxis = Vector3d.ZAxis;
            localWarnings.Add("Axis ambiguity detected; clamped Z axis to world up.");
        }
        var yAxis = Vector3d.CrossProduct(zAxis, xAxis);
        yAxis = NormalizeSafe(yAxis, Vector3d.YAxis);
        zAxis = Vector3d.CrossProduct(xAxis, yAxis);
        zAxis = NormalizeSafe(zAxis, Vector3d.ZAxis);
        xAxis = NormalizeSafe(xAxis, Vector3d.XAxis);
        candidates.Add(FrameCandidate(
            "frame:spread_fallback",
            originPoint,
            xAxis,
            yAxis,
            zAxis,
            "spread_fallback",
            0.65,
            objectCount,
            null,
            symmetryRisk,
            localWarnings
        ));

        Plane fitPlane;
        var fitResult = Plane.FitPlaneToPoints(points, out fitPlane);
        if (fitResult == PlaneFitResult.Success)
        {
            var planeWarnings = new List<string>();
            var avgDist = points.Select(p => Math.Abs(fitPlane.DistanceTo(p))).Average();
            var diag = (points.Max(p => p.X) - points.Min(p => p.X))
                       + (points.Max(p => p.Y) - points.Min(p => p.Y))
                       + (points.Max(p => p.Z) - points.Min(p => p.Z))
                       + 1e-6;
            var confidence = Math.Max(0.35, Math.Min(0.92, 1.0 - (avgDist / diag)));
            var planarityScore = Math.Max(0.0, Math.Min(1.0, 1.0 - (avgDist / diag)));
            candidates.Add(FrameCandidate(
                "frame:plane_fit",
                fitPlane.Origin,
                NormalizeSafe(fitPlane.XAxis, Vector3d.XAxis),
                NormalizeSafe(fitPlane.YAxis, Vector3d.YAxis),
                NormalizeSafe(fitPlane.ZAxis, Vector3d.ZAxis),
                "plane_fit",
                confidence,
                objectCount,
                planarityScore,
                symmetryRisk,
                planeWarnings
            ));
        }
        else
        {
            warnings.Add("Plane fitting failed; candidate omitted.");
        }

        return candidates
            .OrderByDescending(c => Convert.ToDouble(c["confidence"]))
            .ToList();
    }

    private static Point3d ReadCentroid(RhinoObject obj)
    {
        var geometry = obj.Geometry;
        if (geometry is null)
        {
            return Point3d.Origin;
        }
        var bbox = geometry.GetBoundingBox(true);
        if (!bbox.IsValid)
        {
            bbox = geometry.GetBoundingBox(false);
        }
        return bbox.IsValid ? bbox.Center : Point3d.Origin;
    }

    private static Vector3d AxisFromFarthestPair(IReadOnlyList<Point3d> points)
    {
        var best = Vector3d.XAxis;
        var maxDistance = -1.0;
        for (var i = 0; i < points.Count; i++)
        {
            for (var j = i + 1; j < points.Count; j++)
            {
                var vector = points[j] - points[i];
                var distance = vector.SquareLength;
                if (distance > maxDistance)
                {
                    maxDistance = distance;
                    best = NormalizeSafe(vector, Vector3d.XAxis);
                }
            }
        }
        return best;
    }

    private static Vector3d NormalFromSmallestSpread(IReadOnlyList<Point3d> points)
    {
        var xSpread = points.Max(p => p.X) - points.Min(p => p.X);
        var ySpread = points.Max(p => p.Y) - points.Min(p => p.Y);
        var zSpread = points.Max(p => p.Z) - points.Min(p => p.Z);
        if (xSpread <= ySpread && xSpread <= zSpread)
        {
            return Vector3d.XAxis;
        }
        if (ySpread <= xSpread && ySpread <= zSpread)
        {
            return Vector3d.YAxis;
        }
        return Vector3d.ZAxis;
    }

    private static Point3d Average(IReadOnlyList<Point3d> points)
    {
        var x = points.Average(p => p.X);
        var y = points.Average(p => p.Y);
        var z = points.Average(p => p.Z);
        return new Point3d(x, y, z);
    }

    private static Vector3d NormalizeSafe(Vector3d vector, Vector3d fallback)
    {
        if (vector.IsTiny(1e-9))
        {
            return fallback;
        }
        vector.Unitize();
        return vector;
    }

    private static List<double> ToList(Point3d point)
    {
        return new List<double> { point.X, point.Y, point.Z };
    }

    private static List<double> ToList(Vector3d vector)
    {
        return new List<double> { vector.X, vector.Y, vector.Z };
    }

    private static Dictionary<string, object> FrameCandidate(
        string frameId,
        Point3d origin,
        Vector3d xAxis,
        Vector3d yAxis,
        Vector3d zAxis,
        string method,
        double confidence,
        int objectCountUsed,
        double? planarityScore,
        string symmetryRisk,
        IReadOnlyList<string> warnings
    )
    {
        var basis = new Dictionary<string, object>
        {
            ["object_count_used"] = objectCountUsed,
            ["symmetry_risk"] = symmetryRisk
        };
        if (planarityScore.HasValue)
        {
            basis["planarity_score"] = Math.Round(planarityScore.Value, 4);
        }
        return new Dictionary<string, object>
        {
            ["frame_id"] = frameId,
            ["origin"] = ToList(origin),
            ["x_axis"] = ToList(xAxis),
            ["y_axis"] = ToList(yAxis),
            ["z_axis"] = ToList(zAxis),
            ["method"] = method,
            ["confidence"] = Math.Round(confidence, 4),
            ["basis"] = basis,
            ["warnings"] = warnings.Cast<object>().ToList()
        };
    }

    private static string EstimateSymmetryRisk(IReadOnlyList<Point3d> points)
    {
        if (points.Count < 3)
        {
            return "unknown";
        }
        var xSpread = points.Max(p => p.X) - points.Min(p => p.X);
        var ySpread = points.Max(p => p.Y) - points.Min(p => p.Y);
        var zSpread = points.Max(p => p.Z) - points.Min(p => p.Z);
        var spreads = new[] { xSpread, ySpread, zSpread }.OrderByDescending(v => v).ToArray();
        var ratio = spreads[0] > 1e-9 ? spreads[1] / spreads[0] : 1.0;
        if (ratio > 0.9) return "high";
        if (ratio > 0.75) return "medium";
        return "low";
    }

    private static (string frameId, Dictionary<string, object> basis) SelectRecommendedFrame(IReadOnlyList<Dictionary<string, object>> candidates)
    {
        if (candidates.Count == 0)
        {
            return (string.Empty, new Dictionary<string, object>
            {
                ["policy"] = "max_confidence",
                ["reason"] = "no_candidates"
            });
        }

        var maxConfidence = candidates.Max(c => Convert.ToDouble(c["confidence"]));
        var topCandidates = candidates
            .Where(c => Math.Abs(Convert.ToDouble(c["confidence"]) - maxConfidence) < 1e-9)
            .ToList();
        var recommended = topCandidates
            .OrderBy(c => c["frame_id"]?.ToString()?.Equals("frame:plane_fit", StringComparison.OrdinalIgnoreCase) == true ? 0 : 1)
            .ThenBy(c => c["frame_id"]?.ToString())
            .First();

        var recommendedId = recommended["frame_id"]?.ToString() ?? string.Empty;
        var recommendedConfidence = Convert.ToDouble(recommended["confidence"]);
        var followsMax = Math.Abs(recommendedConfidence - maxConfidence) < 1e-9;
        var basis = new Dictionary<string, object>
        {
            ["policy"] = "max_confidence",
            ["follows_max_confidence"] = followsMax
        };
        if (topCandidates.Count > 1)
        {
            basis["reason"] = "tie_break_prefer_plane_fit_then_frame_id";
        }
        else if (!followsMax)
        {
            basis["reason"] = "manual_override";
        }
        return (recommendedId, basis);
    }
}

