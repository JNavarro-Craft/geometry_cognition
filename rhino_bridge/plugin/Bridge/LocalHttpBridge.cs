using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Rhino;
using RhinoPrefabGeometryPlugin.Services;
using RhinoPrefabGeometryPlugin.Utils;

namespace RhinoPrefabGeometryPlugin.Bridge;

public class LocalHttpBridge
{
    private readonly HttpListener _listener;
    private readonly SceneService _sceneService;
    private readonly FamilyService _familyService;
    private readonly FrameService _frameService;
    private readonly InstanceService _instanceService;
    private readonly NeutralGeometryService _neutralGeometryService;
    private CancellationTokenSource? _cts;
    private Task? _serveTask;

    public LocalHttpBridge(string prefix)
    {
        _listener = new HttpListener();
        _listener.Prefixes.Add(prefix);
        _sceneService = new SceneService();
        _familyService = new FamilyService();
        _frameService = new FrameService();
        _instanceService = new InstanceService();
        _neutralGeometryService = new NeutralGeometryService();
    }

    public void Start()
    {
        _cts = new CancellationTokenSource();
        _listener.Start();
        _serveTask = Task.Run(() => ServeLoop(_cts.Token));
    }

    public void Stop()
    {
        try
        {
            _cts?.Cancel();
            _listener.Stop();
            _serveTask?.Wait(TimeSpan.FromSeconds(1));
        }
        catch
        {
            // Best effort shutdown.
        }
    }

    private async Task ServeLoop(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            HttpListenerContext? context = null;
            try
            {
                context = await _listener.GetContextAsync().ConfigureAwait(false);
                HandleRequest(context);
            }
            catch (HttpListenerException)
            {
                // Listener was closed.
                break;
            }
            catch (Exception ex)
            {
                RhinoApp.WriteLine($"[rhino_prefab_geometry] Bridge error: {ex.Message}");
                if (context is not null)
                {
                    HttpJson.Write(context.Response, 500, HttpJson.Error("Unhandled bridge error"));
                    context.Response.Close();
                }
            }
        }
    }

    private void HandleRequest(HttpListenerContext context)
    {
        var req = context.Request;
        var res = context.Response;
        var path = req.Url?.AbsolutePath?.TrimEnd('/').ToLowerInvariant() ?? "/";
        var isGeometryPath = path.StartsWith("/geometry", StringComparison.OrdinalIgnoreCase);
        var isV1Live = path.StartsWith("/v1/live", StringComparison.OrdinalIgnoreCase);
        var method = req.HttpMethod?.Trim().ToUpperInvariant() ?? string.Empty;
        var allowedMethod =
            (isV1Live && path == "/v1/live/scene/summary" && method == "GET")
            || (isV1Live && path == "/v1/live/objects/query" && method == "POST")
            || (isV1Live && path == "/v1/live/definitions" && method == "GET")
            || (isV1Live && path == "/v1/live/definition_objects" && method == "GET")
            || (isV1Live
                && path.StartsWith("/v1/live/objects/", StringComparison.OrdinalIgnoreCase)
                && !string.Equals(path, "/v1/live/objects/query", StringComparison.OrdinalIgnoreCase)
                && method == "GET")
            || (!isGeometryPath && !isV1Live && method == "GET")
            || (isGeometryPath && path == "/geometry/health" && method == "GET")
            || (isGeometryPath && (path == "/geometry/extract_scene" || path == "/geometry/extract_objects" || path == "/geometry/verify_relations") && method == "POST");
        if (!allowedMethod)
        {
            HttpJson.Write(res, 405, HttpJson.Error("Method not allowed", "bad_request"));
            res.Close();
            return;
        }

        try
        {
            if (TryHandleV1Live(path, method, req, res))
            {
                res.Close();
                return;
            }

            switch (path)
            {
                case "":
                case "/":
                case "/health":
                    HttpJson.Write(res, 200, new Dictionary<string, object>
                    {
                        ["status"] = "ok",
                        ["service"] = "rhino_prefab_geometry_bridge"
                    });
                    break;
                case "/geometry/health":
                    HttpJson.Write(res, 200, new Dictionary<string, object>
                    {
                        ["status"] = "ok",
                        ["service"] = "rhino_geometry_neutral_bridge",
                        ["mode"] = "neutral_geometry"
                    });
                    break;
                case "/geometry/extract_scene":
                    var sceneExtraction = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _neutralGeometryService.ExtractScene(doc);
                    });
                    HttpJson.Write(res, 200, sceneExtraction);
                    break;
                case "/geometry/extract_objects":
                    var body = ReadRequestBody(req);
                    var requestedObjectIds = ParseRequestedObjectIds(req, body);
                    var objectsExtraction = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _neutralGeometryService.ExtractObjects(doc, requestedObjectIds);
                    });
                    HttpJson.Write(res, 200, objectsExtraction);
                    break;
                case "/geometry/verify_relations":
                    var verifyBody = ReadRequestBody(req);
                    var verifyRequest = ParseVerifyRelationsRequest(verifyBody);
                    var verifyOutput = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _neutralGeometryService.VerifyRelations(
                            doc,
                            verifyRequest.Relations,
                            verifyRequest.Tolerance ?? new NeutralGeometryService.VerificationTolerance()
                        );
                    });
                    HttpJson.Write(res, 200, verifyOutput);
                    break;

                case "/doc-info":
                    var info = ExecuteOnUiThread(() =>
                    {
                        var doc = RhinoDoc.ActiveDoc;
                        if (doc is null)
                        {
                            return new Dictionary<string, object?>
                            {
                                ["has_active_doc"] = false
                            };
                        }
                        return new Dictionary<string, object?>
                        {
                            ["has_active_doc"] = true,
                            ["name"] = doc.Name,
                            ["path"] = doc.Path,
                            ["object_count"] = doc.Objects.Count
                        };
                    });
                    HttpJson.Write(res, 200, info);
                    break;

                case "/summarize-model":
                    var summary = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _sceneService.SummarizeModel(doc);
                    });
                    HttpJson.Write(res, 200, summary);
                    break;

                case "/list-groups":
                    var groups = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _instanceService.ListGroups(doc);
                    });
                    HttpJson.Write(res, 200, groups);
                    break;

                case "/list-ungrouped-objects":
                    var ungrouped = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _instanceService.ListUngroupedObjects(doc);
                    });
                    HttpJson.Write(res, 200, ungrouped);
                    break;

                case "/inspect-metadata-coverage":
                    var metadataCoverage = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _instanceService.InspectMetadataCoverage(doc);
                    });
                    HttpJson.Write(res, 200, metadataCoverage);
                    break;

                case "/get-object-summary":
                    var objectId = req.QueryString["object_id"]?.Trim() ?? string.Empty;
                    if (string.IsNullOrWhiteSpace(objectId))
                    {
                        HttpJson.Write(res, 400, HttpJson.Error("Missing query parameter: object_id", "bad_request"));
                        break;
                    }
                    var objectSummary = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _instanceService.GetObjectSummary(doc, objectId);
                    });
                    HttpJson.Write(res, 200, objectSummary);
                    break;

                case "/get-object-neighborhood":
                    var anchorObjectId = req.QueryString["object_id"]?.Trim() ?? string.Empty;
                    var mode = req.QueryString["mode"]?.Trim() ?? "spatial";
                    if (string.IsNullOrWhiteSpace(anchorObjectId))
                    {
                        HttpJson.Write(res, 400, HttpJson.Error("Missing query parameter: object_id", "bad_request"));
                        break;
                    }
                    var neighborhood = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _instanceService.GetObjectNeighborhood(doc, anchorObjectId, mode);
                    });
                    HttpJson.Write(res, 200, neighborhood);
                    break;

                case "/list-named-families":
                    var prefixes = ReadListQueryParam(req, "prefixes");
                    var families = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _familyService.ListNamedFamilies(doc, prefixes);
                    });
                    HttpJson.Write(res, 200, families);
                    break;

                case "/summarize-family":
                    var name = req.QueryString["name"]?.Trim() ?? string.Empty;
                    if (string.IsNullOrWhiteSpace(name))
                    {
                        HttpJson.Write(res, 400, HttpJson.Error("Missing query parameter: name", "bad_request"));
                        break;
                    }
                    var family = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _familyService.SummarizeFamily(doc, name);
                    });
                    HttpJson.Write(res, 200, family);
                    break;

                case "/get-family-instances":
                    var familyInstancesName = req.QueryString["name"]?.Trim() ?? string.Empty;
                    if (string.IsNullOrWhiteSpace(familyInstancesName))
                    {
                        HttpJson.Write(res, 400, HttpJson.Error("Missing query parameter: name", "bad_request"));
                        break;
                    }
                    var instances = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _familyService.GetFamilyInstances(doc, familyInstancesName);
                    });
                    HttpJson.Write(res, 200, instances);
                    break;

                case "/get-instance-local-frame":
                    var legacyName = req.QueryString["name"]?.Trim() ?? string.Empty;
                    var legacyGroupId = req.QueryString["group_id"]?.Trim() ?? string.Empty;
                    if (string.IsNullOrWhiteSpace(legacyName) || string.IsNullOrWhiteSpace(legacyGroupId))
                    {
                        HttpJson.Write(res, 400, HttpJson.Error("Missing query parameters: name and group_id are required", "bad_request"));
                        break;
                    }
                    var legacyFrame = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _frameService.GetLegacySingleFrame(doc, _instanceService, $"grp:{legacyGroupId}");
                    });
                    HttpJson.Write(res, 200, legacyFrame);
                    break;

                case "/get-instance-frame-candidates":
                    var instanceId = req.QueryString["instance_id"]?.Trim() ?? string.Empty;
                    if (string.IsNullOrWhiteSpace(instanceId))
                    {
                        HttpJson.Write(res, 400, HttpJson.Error("Missing query parameter: instance_id", "bad_request"));
                        break;
                    }
                    var frameCandidates = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _frameService.GetInstanceFrameCandidates(doc, _instanceService, instanceId);
                    });
                    HttpJson.Write(res, 200, frameCandidates);
                    break;

                case "/get-instance-geometry":
                    var geometryInstanceId = req.QueryString["instance_id"]?.Trim() ?? string.Empty;
                    if (string.IsNullOrWhiteSpace(geometryInstanceId))
                    {
                        HttpJson.Write(res, 400, HttpJson.Error("Missing query parameter: instance_id", "bad_request"));
                        break;
                    }
                    var geometry = ExecuteOnUiThread(() =>
                    {
                        var doc = RequireActiveDoc();
                        return _instanceService.GetInstanceGeometry(doc, geometryInstanceId);
                    });
                    HttpJson.Write(res, 200, geometry);
                    break;

                case "/detect-duplicate-groups":
                case "/inspect-usertext-schema":
                    HttpJson.Write(res, 501, HttpJson.Error("Endpoint planned but not implemented yet.", "not_implemented"));
                    break;

                default:
                    HttpJson.Write(res, 404, HttpJson.Error("Route not found", "not_found"));
                    break;
            }
        }
        catch (InvalidOperationException ex)
        {
            HttpJson.Write(res, 400, HttpJson.Error(ex.Message, "bad_request"));
        }
        catch (KeyNotFoundException ex)
        {
            HttpJson.Write(res, 404, HttpJson.Error(ex.Message, "not_found"));
        }
        catch (Exception ex)
        {
            RhinoApp.WriteLine($"[rhino_prefab_geometry] Request error on {path}: {ex.Message}");
            HttpJson.Write(res, 500, HttpJson.Error("Internal server error", "internal_error"));
        }

        res.Close();
    }

    private static RhinoDoc RequireActiveDoc()
    {
        return RhinoDoc.ActiveDoc ?? throw new InvalidOperationException("No active RhinoDoc.");
    }

    private bool TryHandleV1Live(string path, string method, HttpListenerRequest req, HttpListenerResponse res)
    {
        if (!path.StartsWith("/v1/live", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (path == "/v1/live/scene/summary" && method == "GET")
        {
            var sampleLimit = ParseIntQuery(req, "sample_limit", 20, 0, 100);
            var summary = ExecuteOnUiThread(() =>
            {
                var doc = RequireActiveDoc();
                return _neutralGeometryService.LiveSceneSummary(doc, sampleLimit);
            });
            HttpJson.Write(res, 200, summary);
            return true;
        }

        if (path == "/v1/live/objects/query" && method == "POST")
        {
            var body = ReadRequestBody(req);
            var queryRequest = NeutralGeometryService.ParseLiveObjectsQuery(body);
            var queryResult = ExecuteOnUiThread(() =>
            {
                var doc = RequireActiveDoc();
                return _neutralGeometryService.LiveQueryObjects(doc, queryRequest);
            });
            HttpJson.Write(res, 200, queryResult);
            return true;
        }

        if (path == "/v1/live/definitions" && method == "GET")
        {
            var defs = ExecuteOnUiThread(() =>
            {
                var doc = RequireActiveDoc();
                return _neutralGeometryService.LiveListDefinitions(doc);
            });
            HttpJson.Write(res, 200, defs);
            return true;
        }

        if (path == "/v1/live/definition_objects" && method == "GET")
        {
            var defName = req.QueryString["name"]?.Trim() ?? string.Empty;
            if (string.IsNullOrWhiteSpace(defName))
            {
                HttpJson.Write(res, 400, HttpJson.Error("Missing required query param: name", "bad_request"));
                return true;
            }
            var resolveInstances = string.Equals(req.QueryString["instances"]?.Trim(), "true", StringComparison.OrdinalIgnoreCase);
            var defObjects = ExecuteOnUiThread(() =>
            {
                var doc = RequireActiveDoc();
                return _neutralGeometryService.LiveGetDefinitionObjects(doc, defName, resolveInstances);
            });
            HttpJson.Write(res, 200, defObjects);
            return true;
        }

        if (path.StartsWith("/v1/live/objects/", StringComparison.OrdinalIgnoreCase) && method == "GET")
        {
            var idPart = path.Substring("/v1/live/objects/".Length).Trim();
            if (string.IsNullOrWhiteSpace(idPart))
            {
                HttpJson.Write(res, 400, HttpJson.Error("Missing object id in path", "bad_request"));
                return true;
            }
            var detailLevel = req.QueryString["detail_level"]?.Trim() ?? "basic";
            var userTextMode = req.QueryString["user_text"]?.Trim() ?? "keys";
            var detail = ExecuteOnUiThread(() =>
            {
                var doc = RequireActiveDoc();
                return _neutralGeometryService.LiveGetObject(doc, idPart, detailLevel, userTextMode);
            });
            HttpJson.Write(res, 200, detail);
            return true;
        }

        HttpJson.Write(res, 404, HttpJson.Error("Route not found", "not_found"));
        return true;
    }

    private static int ParseIntQuery(HttpListenerRequest req, string key, int defaultValue, int min, int max)
    {
        var raw = req.QueryString[key]?.Trim();
        if (string.IsNullOrWhiteSpace(raw) || !int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var v))
        {
            return Math.Max(min, Math.Min(max, defaultValue));
        }
        return Math.Max(min, Math.Min(max, v));
    }

    private static List<string> ReadListQueryParam(HttpListenerRequest req, string key)
    {
        var values = req.QueryString.GetValues(key);
        if (values is null || values.Length == 0)
        {
            return new List<string>();
        }
        return values
            .SelectMany(v => (v ?? string.Empty).Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries))
            .Select(v => v.Trim())
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static string ReadRequestBody(HttpListenerRequest req)
    {
        if (!req.HasEntityBody || req.InputStream is null)
        {
            return string.Empty;
        }
        using var reader = new System.IO.StreamReader(req.InputStream, req.ContentEncoding ?? Encoding.UTF8);
        return reader.ReadToEnd();
    }

    private static List<string> ParseRequestedObjectIds(HttpListenerRequest req, string body)
    {
        var ids = new List<string>();
        ids.AddRange(ReadListQueryParam(req, "object_ids"));
        ids.AddRange(ReadListQueryParam(req, "object_id"));
        if (!string.IsNullOrWhiteSpace(body))
        {
            var guidMatches = System.Text.RegularExpressions.Regex.Matches(
                body,
                @"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
            );
            foreach (System.Text.RegularExpressions.Match match in guidMatches)
            {
                if (match.Success)
                {
                    ids.Add(match.Value);
                }
            }
        }
        return ids
            .Select(v => (v ?? string.Empty).Trim())
            .Where(v => !string.IsNullOrWhiteSpace(v))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static VerifyRelationsEnvelope ParseVerifyRelationsRequest(string body)
    {
        if (string.IsNullOrWhiteSpace(body))
        {
            throw new InvalidOperationException("Missing request body for /geometry/verify_relations.");
        }
        try
        {
            using var ms = new MemoryStream(Encoding.UTF8.GetBytes(body));
            var serializer = new DataContractJsonSerializer(typeof(VerifyRelationsEnvelope));
            var parsed = serializer.ReadObject(ms) as VerifyRelationsEnvelope;
            if (parsed is null)
            {
                throw new InvalidOperationException("Invalid verify_relations payload.");
            }
            if (parsed.Relations is null || parsed.Relations.Count == 0)
            {
                throw new InvalidOperationException("verify_relations requires a non-empty relations list.");
            }
            return parsed;
        }
        catch (SerializationException ex)
        {
            throw new InvalidOperationException($"Invalid JSON payload: {ex.Message}");
        }
    }

    private static T ExecuteOnUiThread<T>(Func<T> action)
    {
        var tcs = new TaskCompletionSource<T>();
        RhinoApp.InvokeOnUiThread(() =>
        {
            try
            {
                tcs.SetResult(action());
            }
            catch (Exception ex)
            {
                tcs.SetException(ex);
            }
        });
        return tcs.Task.GetAwaiter().GetResult();
    }

    [DataContract]
    private sealed class VerifyRelationsEnvelope
    {
        [DataMember(Name = "relations")]
        public List<NeutralGeometryService.RelationVerificationRequest> Relations { get; set; } = new();

        [DataMember(Name = "tolerance")]
        public NeutralGeometryService.VerificationTolerance? Tolerance { get; set; }
    }
}

