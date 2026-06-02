using System;
using System.Collections.Generic;
using System.Collections;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Types;
using SAP2000v1;

namespace RhinoSAP.Grasshopper
{
    /// <summary>
    /// Asigna cargas distribuidas uniformes a FrameObj existentes en SAP2000.
    /// No ejecuta análisis ni modifica geometría; solo prepara el modelo.
    /// </summary>
    public class AssignFrameDistributedLoads : GH_Component
    {
        private bool _lastRunState;
        private bool _lastSuccess;
        private List<string> _lastMessages = new();

        public AssignFrameDistributedLoads()
            : base("Assign Frame Distributed Loads", "FrameUdl",
                  "Asigna cargas distribuidas uniformes a frames existentes en SAP2000.",
                  "RhinoSAP", "Loads")
        {
        }

        public override Guid ComponentGuid => new Guid("B7B6A6F1-5F9F-47D8-A188-7058422D6E35");
        protected override System.Drawing.Bitmap Icon => null;

        protected override void RegisterInputParams(GH_InputParamManager pManager)
        {
            pManager.AddGenericParameter("SapModel", "Model", "Instancia activa de cSapModel.", GH_ParamAccess.item);
            pManager.AddTextParameter("Frames", "Frames", "Nombres de FrameObj a cargar (estructura en árbol).", GH_ParamAccess.tree);
            pManager.AddTextParameter("LoadPattern", "LoadPat", "Patrón de carga por rama (igual estructura).", GH_ParamAccess.tree);
            pManager.AddTextParameter("CoordinateSystem", "CSys", "Sistema de coordenadas por rama. Default GLOBAL.", GH_ParamAccess.tree);
            pManager.AddTextParameter("LoadDirection", "Dir", "Dirección: Gravity, Local1, Local2, Local3, X, Y, Z.", GH_ParamAccess.tree);
            pManager.AddTextParameter("LoadType", "Type", "Tipo de carga: Force o Displ. Default Force.", GH_ParamAccess.tree);
            pManager.AddNumberParameter("UniformLoad", "w", "Carga distribuida uniforme (kgf/m) por rama.", GH_ParamAccess.tree);
            pManager.AddBooleanParameter("Run", "Run", "Ejecuta la asignación cuando es true.", GH_ParamAccess.item, false);
        }

        protected override void RegisterOutputParams(GH_OutputParamManager pManager)
        {
            pManager.AddGenericParameter("SapModel", "Model", "SapModel modificado (passthrough).", GH_ParamAccess.item);
            pManager.AddTextParameter("Frames", "Frames", "Frames a los que se intentó asignar carga (passthrough).", GH_ParamAccess.list);
            pManager.AddTextParameter("Messages", "Msg", "Mensajes de la asignación.", GH_ParamAccess.list);
            pManager.AddBooleanParameter("Success", "OK", "True si todas las asignaciones devolvieron ret=0.", GH_ParamAccess.item);
        }

        protected override void SolveInstance(IGH_DataAccess DA)
        {
            object sapObj = null;
            if (!DA.GetData(0, ref sapObj) || sapObj == null)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "SapModel inválido.");
                OutputCached(DA, "[ERROR] SapModel inválido.");
                return;
            }

            GH_Structure<GH_String> framesTree;
            if (!DA.GetDataTree(1, out framesTree) || framesTree == null || framesTree.PathCount == 0)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "Lista de frames vacía.");
                OutputCached(DA, "[ERROR] Lista de frames vacía.");
                return;
            }

            GH_Structure<GH_String> patternTree;
            DA.GetDataTree(2, out patternTree);
            GH_Structure<GH_String> csysTree;
            DA.GetDataTree(3, out csysTree);
            GH_Structure<GH_String> dirTree;
            DA.GetDataTree(4, out dirTree);
            GH_Structure<GH_String> typeTree;
            DA.GetDataTree(5, out typeTree);
            GH_Structure<GH_Number> loadTree;
            DA.GetDataTree(6, out loadTree);

            bool run = false;
            DA.GetData(7, ref run);

            var sapModel = ExtractSapModel(sapObj);
            if (sapModel == null)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "No se pudo convertir SapModel.");
                OutputCached(DA, "[ERROR] Conversión SapModel fallida.");
                return;
            }

            bool shouldExecute = run && !_lastRunState;
            _lastRunState = run;

            if (!shouldExecute)
            {
                var passive = new List<string>(_lastMessages);
                passive.Add(run
                    ? "[INFO] Run permanece en true. Libere y vuelva a pulsar para reejecutar."
                    : "[INFO] Run = false. En espera de activación.");
                DA.SetData(0, sapObj);
                DA.SetDataList(1, FlattenFrames(framesTree));
                DA.SetDataList(2, passive);
                DA.SetData(3, _lastSuccess);
                return;
            }

            var messages = new List<string>();
            bool success = true;

            // Iterar por rama: cada rama representa un frame; los ítems de la rama son cargas.
            for (int i = 0; i < framesTree.PathCount; i++)
            {
                var path = framesTree.Paths[i];
                var frameBranch = framesTree.get_Branch(path);
                if (frameBranch == null || frameBranch.Count != 1)
                {
                    messages.Add($"[ERROR] La rama {path} debe contener exactamente un Frame.");
                    success = false;
                    continue;
                }

                string frame = frameBranch[0] is GH_String gsFrame ? gsFrame.Value : frameBranch[0]?.ToString();
                if (string.IsNullOrWhiteSpace(frame))
                {
                    messages.Add($"[ERROR] Frame vacío en rama {path}.");
                    success = false;
                    continue;
                }

                var patternBranch = patternTree?.get_Branch(path);
                var csysBranch = csysTree?.get_Branch(path);
                var dirBranch = dirTree?.get_Branch(path);
                var typeBranch = typeTree?.get_Branch(path);
                var loadBranch = loadTree?.get_Branch(path);

                int loadCount = loadBranch?.Count ?? 0;
                int patternCount = patternBranch?.Count ?? 0;
                if (loadCount == 0 || patternCount == 0 || loadCount != patternCount)
                {
                    messages.Add($"[ERROR] Desalineación o ausencia de cargas en rama {path} (Frame {frame}). loadCount={loadCount}, patternCount={patternCount}");
                    success = false;
                    continue;
                }

                for (int j = 0; j < loadCount; j++)
                {
                    string loadPat = GetString(patternBranch, j, defaultValue: string.Empty);
                    if (string.IsNullOrWhiteSpace(loadPat))
                    {
                        messages.Add($"[ERROR] LoadPattern vacío en rama {path} (idx {j}) para frame {frame}.");
                        success = false;
                        continue;
                    }

                    string csys = GetString(csysBranch, j, defaultValue: "GLOBAL");
                    string dir = GetString(dirBranch, j, defaultValue: "Gravity");
                    string type = GetString(typeBranch, j, defaultValue: "Force");
                    double uniform = GetNumber(loadBranch, j, defaultValue: 0.0);

                    try
                    {
                        int loadType = ParseLoadType(type);
                        int loadDir = ParseLoadDirection(dir);
                        int ret = sapModel.FrameObj.SetLoadDistributed(
                            frame,
                            loadPat,
                            loadType,
                            loadDir,
                            0.0,
                            1.0,
                            uniform,
                            uniform,
                            csys,
                            false);

                        if (ret != 0)
                        {
                            messages.Add($"[ERROR] SetLoadDistributed falló para '{frame}' (patrón '{loadPat}', idx {j}) (ret={ret}).");
                            success = false;
                        }
                        else
                        {
                            messages.Add($"[OK] Carga distribuida asignada a '{frame}' patrón '{loadPat}' (idx {j}).");
                        }
                    }
                    catch (Exception ex)
                    {
                        messages.Add($"[ERROR] Excepción al asignar a '{frame}' patrón '{loadPat}' (idx {j}): {ex.Message}");
                        success = false;
                    }
                }
            }

            _lastMessages = messages;
            _lastSuccess = success;

            DA.SetData(0, sapObj);
            DA.SetDataList(1, FlattenFrames(framesTree));
            DA.SetDataList(2, messages);
            DA.SetData(3, success);
        }

        private void OutputCached(IGH_DataAccess DA, string extraMessage)
        {
            var msgs = new List<string>(_lastMessages);
            if (!string.IsNullOrEmpty(extraMessage))
                msgs.Add(extraMessage);

            DA.SetData(0, null);
            DA.SetDataList(1, Array.Empty<string>());
            DA.SetDataList(2, msgs);
            DA.SetData(3, _lastSuccess);
        }

        private static cSapModel ExtractSapModel(object obj)
        {
            if (obj is cSapModel direct)
                return direct;
            if (obj is GH_ObjectWrapper wrap && wrap.Value is cSapModel wrapped)
                return wrapped;
            return null;
        }

        private int ParseLoadDirection(string dir)
        {
            // Map manual a códigos esperados por SAP2000 (FrameObj.SetLoadDistributed).
            // Ajustado: Gravity se fuerza al código 10 (observado en SAP como gravity), proyecciones a 8/9/10 solo si se pide explícitamente.
            if (string.IsNullOrWhiteSpace(dir)) return 10; // Gravity por defecto
            switch (dir.Trim().ToLowerInvariant())
            {
                case "local1":
                case "1":
                    return 1;
                case "local2":
                case "2":
                    return 2;
                case "local3":
                case "3":
                    return 3;
                case "x":
                case "globalx":
                    return 4;
                case "y":
                case "globaly":
                    return 5;
                case "z":
                case "globalz":
                    return 6;
                case "gravity":
                case "grav":
                case "g":
                    return 10;
                case "projx":
                case "xproj":
                    return 8;
                case "projy":
                case "yproj":
                    return 9;
                case "projz":
                case "zproj":
                    return 11;
                default:
                    return 10; // Gravity por defecto
            }
        }

        private int ParseLoadType(string type)
        {
            // Mapeo manual según firma SetLoadDistributed: 1=Force, 2=Displ
            if (string.IsNullOrWhiteSpace(type)) return 1;
            switch (type.Trim().ToLowerInvariant())
            {
                case "force":
                case "f":
                    return 1;
                case "displ":
                case "displacement":
                case "d":
                    return 2;
                default:
                    return 1;
            }
        }

        private List<string> FlattenFrames(GH_Structure<GH_String> framesTree)
        {
            var list = new List<string>();
            if (framesTree == null) return list;
            foreach (var branch in framesTree.Branches)
            {
                if (branch == null || branch.Count == 0) continue;
                if (branch[0] is GH_String gs && !string.IsNullOrWhiteSpace(gs.Value))
                    list.Add(gs.Value);
                else if (branch[0] != null)
                    list.Add(branch[0].ToString());
            }
            return list;
        }

        private string GetString(IList branch, int index, string defaultValue)
        {
            if (branch == null || index < 0 || index >= branch.Count || branch[index] == null)
                return defaultValue;
            if (branch[index] is GH_String gs) return gs.Value;
            return branch[index].ToString();
        }

        private double GetNumber(IList branch, int index, double defaultValue)
        {
            if (branch == null || index < 0 || index >= branch.Count || branch[index] == null)
                return defaultValue;
            if (branch[index] is GH_Number gn) return gn.Value;
            if (double.TryParse(branch[index].ToString(), out var d)) return d;
            return defaultValue;
        }
    }
}

