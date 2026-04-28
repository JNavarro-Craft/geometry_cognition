using Rhino;
using Rhino.PlugIns;
using RhinoPrefabGeometryPlugin.Bridge;
using System;
using System.Net;

namespace RhinoPrefabGeometryPlugin.Plugin;

public class RhinoPrefabGeometryPlugin : PlugIn
{
    public static RhinoPrefabGeometryPlugin? Instance { get; private set; }
    private static readonly object BridgeLock = new();
    public static bool IsRunning { get; private set; }

    private LocalHttpBridge? _bridge;
    private int _bridgePort = 8765;

    public RhinoPrefabGeometryPlugin()
    {
        Instance = this;
    }

    protected override LoadReturnCode OnLoad(ref string errorMessage)
    {
        EnsureBridgeStarted();
        return LoadReturnCode.Success;
    }

    protected override void OnShutdown()
    {
        lock (BridgeLock)
        {
            _bridge?.Stop();
            _bridge = null;
            IsRunning = false;
        }
        RhinoApp.WriteLine($"[rhino_prefab_geometry] Local bridge stopped.");
        base.OnShutdown();
    }

    public static bool EnsureBridgeStarted(out string message)
    {
        var plugin = Instance;
        if (plugin is null)
        {
            message = "RhinoAI bridge plugin instance is unavailable.";
            return false;
        }
        return plugin.EnsureBridgeStartedInternal(out message);
    }

    public bool EnsureBridgeStarted()
    {
        return EnsureBridgeStartedInternal(out _);
    }

    public int CurrentPort => _bridgePort;

    private bool EnsureBridgeStartedInternal(out string message)
    {
        lock (BridgeLock)
        {
            if (IsRunning)
            {
                message = $"RhinoAI bridge already running on http://127.0.0.1:{_bridgePort}";
                return false;
            }

            _bridgePort = ResolvePort();
            var prefix = $"http://127.0.0.1:{_bridgePort}/";
            try
            {
                _bridge = new LocalHttpBridge(prefix);
                _bridge.Start();
                IsRunning = true;
                message = $"RhinoAI bridge started on http://127.0.0.1:{_bridgePort}";
                RhinoApp.WriteLine($"[rhino_prefab_geometry] Local bridge started at http://127.0.0.1:{_bridgePort}");
                return true;
            }
            catch (HttpListenerException ex)
            {
                _bridge = null;
                IsRunning = false;
                message = $"RhinoAI bridge failed to bind port {_bridgePort}: {ex.Message}";
                RhinoApp.WriteLine($"[rhino_prefab_geometry] {message}");
                return false;
            }
            catch (Exception ex)
            {
                _bridge = null;
                IsRunning = false;
                message = $"RhinoAI bridge failed to start: {ex.Message}";
                RhinoApp.WriteLine($"[rhino_prefab_geometry] {message}");
                return false;
            }
        }
    }

    private static int ResolvePort()
    {
        var fromEnv = Environment.GetEnvironmentVariable("RHINOAI_BRIDGE_PORT");
        if (int.TryParse(fromEnv, out var parsed) && parsed > 0 && parsed <= 65535)
        {
            return parsed;
        }
        return 8765;
    }
}

