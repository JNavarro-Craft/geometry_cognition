using System;
using System.Collections.Generic;
using System.Linq;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Types;
using Rhino.Geometry;
using RhinoSAP.Core;
using RhinoSAP.SAP;
using RhinoSAP.Utils;
using SAP2000v1;

namespace RhinoSAP.Grasshopper
{
    /// <summary>
    /// Sincroniza curvas hacia FrameObj en SAP2000.
    /// </summary>
    public class GH_PushCurvesToSAP : GH_Component
    {
        private const string DefaultSectionName = "MGP10_33x73";
        private readonly Dictionary<string, FrameRecord> _registry = new();
        private readonly SapLogger _logger = new();
        private SapFrameSynchronizer _synchronizer;
        private string _lastSection = string.Empty;

        public GH_PushCurvesToSAP()
            : base("Push Curves To SAP", "Curve→SAP",
                  "Sincroniza curvas de GH con barras en SAP2000 (CRUD).",
                  "RhinoSAP", "Connection")
        {
        }

        public override Guid ComponentGuid => new Guid("8E64C573-B58C-4E0C-9CF7-A2F3423A4422");
        protected override System.Drawing.Bitmap Icon => null;

        protected override void RegisterInputParams(GH_InputParamManager pManager)
        {
            pManager.AddCurveParameter("Curves", "C", "Curvas a sincronizar", GH_ParamAccess.tree);
            pManager.AddGenericParameter("SapModel", "Model", "Instancia cSapModel activa", GH_ParamAccess.item);
            pManager.AddTextParameter("Sections", "Sec", "Lista de secciones por curva. Si se deja vacío se usará la sección por defecto.", GH_ParamAccess.list);
            pManager[2].Optional = true;
            pManager.AddBooleanParameter("Auto Run", "Run", "Sincroniza automáticamente en cada recomputo", GH_ParamAccess.item, true);
            pManager.AddBooleanParameter("Sync Trigger", "Sync", "Botón para forzar sincronización cuando Auto Run = false", GH_ParamAccess.item, false);
        }

        protected override void RegisterOutputParams(GH_OutputParamManager pManager)
        {
            pManager.AddTextParameter("Frames", "Frames", "FrameObj activos en SAP", GH_ParamAccess.list);
            pManager.AddTextParameter("Messages", "Msg", "Mensajes detallados", GH_ParamAccess.list);
            pManager.AddBooleanParameter("Success", "OK", "True si no hubo errores", GH_ParamAccess.item);
        }

        protected override void SolveInstance(IGH_DataAccess DA)
        {
            var curvesTree = new GH_Structure<GH_Curve>();
            if (!DA.GetDataTree(0, out curvesTree))
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Warning, "Sin curvas en la entrada.");
                DA.SetDataList(0, new string[0]);
                DA.SetDataList(1, new[] { "Sin curvas." });
                DA.SetData(2, false);
                return;
            }

            object sapModelObj = null;
            if (!DA.GetData(1, ref sapModelObj) || sapModelObj == null)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "SapModel inválido.");
                DA.SetDataList(0, new string[0]);
                DA.SetDataList(1, new[] { "SapModel inválido." });
                DA.SetData(2, false);
                return;
            }

            var sapModel = ExtractSapModel(sapModelObj);
            if (sapModel == null)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "No se pudo convertir SapModel.");
                DA.SetDataList(0, new string[0]);
                DA.SetDataList(1, new[] { "Conversión SapModel fallida." });
                DA.SetData(2, false);
                return;
            }

            var sectionInputs = new List<string>();
            DA.GetDataList(2, sectionInputs);
            bool autoRun = true;
            DA.GetData(3, ref autoRun);

            bool syncTrigger = false;
            DA.GetData(4, ref syncTrigger);

            _synchronizer ??= new SapFrameSynchronizer(_registry, _logger, 1e-6);

            var messages = new List<string>();
            bool success = true;

            var snapshots = BuildSnapshots(curvesTree, messages);

            if (snapshots.Count == 0)
            {
                messages.Add("[WARN] No se generaron curvas válidas para sincronizar.");
                DA.SetDataList(0, new string[0]);
                DA.SetDataList(1, messages);
                DA.SetData(2, false);
                return;
            }

            if (sectionInputs.Count > 0 && sectionInputs.Count != snapshots.Count)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error,
                    $"La cantidad de secciones ({sectionInputs.Count}) debe coincidir con el número de curvas ({snapshots.Count}).");
                DA.SetDataList(0, new string[0]);
                DA.SetDataList(1, new[] { "Error: las listas de curvas y secciones no coinciden." });
                DA.SetData(2, false);
                return;
            }

            var sectionAssignments = BuildSectionAssignments(sectionInputs, snapshots.Count);
            var sectionKey = string.Join("|", sectionAssignments);

            bool sectionChanged = !_lastSection.Equals(sectionKey, StringComparison.OrdinalIgnoreCase);

            bool shouldSync = autoRun || syncTrigger || sectionChanged;

            if (shouldSync)
            {
                var report = _synchronizer.Synchronize(sapModel, snapshots, sectionAssignments);
                messages.AddRange(report.Messages);
                success = report.Success;
                _lastSection = sectionKey;

                if (!autoRun && syncTrigger)
                {
                    messages.Add("[INFO] Sincronización forzada mediante botón Sync.");
                }

                if (sectionChanged)
                {
                    messages.Add("[INFO] Secciones actualizadas.");
                }
            }
            else
            {
                messages.Add("[INFO] Auto Run desactivado y sin cambios pendientes. Se mantienen los datos anteriores.");
            }

            messages.AddRange(_logger.Flush());

            var frames = _registry.Values
                .Select(r => r.FrameName)
                .Distinct()
                .OrderBy(n => n)
                .ToList();

            DA.SetDataList(0, frames);
            DA.SetDataList(1, messages);
            DA.SetData(2, success);
        }

        private static cSapModel ExtractSapModel(object obj)
        {
            if (obj is cSapModel direct)
                return direct;

            if (obj is GH_ObjectWrapper wrapper && wrapper.Value is cSapModel wrapped)
                return wrapped;

            return null;
        }

        private static List<CurveSnapshot> BuildSnapshots(GH_Structure<GH_Curve> tree, List<string> messages)
        {
            var snapshots = new List<CurveSnapshot>();

            foreach (var path in tree.Paths)
            {
                var branch = tree.get_Branch(path);
                for (int i = 0; i < branch.Count; i++)
                {
                    if (branch[i] is not GH_Curve ghCurve || ghCurve.Value == null)
                        continue;

                    var curve = ghCurve.Value.DuplicateCurve();
                    if (curve == null || !curve.IsValid)
                    {
                        messages.Add($"[WARN] Curva inválida en {path}[{i}].");
                        continue;
                    }

                    var start = UnitConversion.ToSap(curve.PointAtStart);
                    var end = UnitConversion.ToSap(curve.PointAtEnd);

                    if (start.DistanceTo(end) < 1e-6)
                    {
                        messages.Add($"[WARN] Curva degenerada en {path}[{i}].");
                        continue;
                    }

                    string id = $"{path}:{i}";
                    snapshots.Add(new CurveSnapshot(id, start, end));
                }
            }

            return snapshots;
        }

        private List<string> BuildSectionAssignments(IList<string> rawSections, int count)
        {
            var result = new List<string>(count);
            bool hasCustom = rawSections is { Count: > 0 };

            for (int i = 0; i < count; i++)
            {
                string section = hasCustom ? rawSections[i] : null;
                if (string.IsNullOrWhiteSpace(section))
                {
                    section = DefaultSectionName;
                }

                result.Add(section.Trim());
            }

            return result;
        }
    }
}

