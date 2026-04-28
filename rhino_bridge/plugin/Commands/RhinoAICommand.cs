using Rhino;
using Rhino.Commands;
using BridgePlugin = RhinoPrefabGeometryPlugin.Plugin.RhinoPrefabGeometryPlugin;

namespace RhinoPrefabGeometryPlugin.Commands;

public class RhinoAICommand : Command
{
    public override string EnglishName => "RhinoAI";

    protected override Result RunCommand(RhinoDoc doc, RunMode mode)
    {
        if (BridgePlugin.IsRunning)
        {
            RhinoApp.WriteLine("RhinoAI bridge already running");
            return Result.Success;
        }

        var started = BridgePlugin.EnsureBridgeStarted(out var message);
        RhinoApp.WriteLine(message);
        return started ? Result.Success : Result.Failure;
    }
}
