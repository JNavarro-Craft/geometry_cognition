using Rhino;
using Rhino.Commands;

namespace RhinoPrefabGeometryPlugin.Commands;

public class RpgBridgeStatusCommand : Command
{
    public override string EnglishName => "RpgBridgeStatus";

    protected override Result RunCommand(RhinoDoc doc, RunMode mode)
    {
        RhinoApp.WriteLine("[rhino_prefab_geometry] Bridge expected at http://127.0.0.1:8765/health");
        return Result.Success;
    }
}

