using System;
using System.Collections.Generic;
using System.Linq;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Types;
using Rhino.Geometry;
using SAP2000v1;
using RhinoSAP.Utils;

namespace RhinoSAP.Grasshopper
{
    /// <summary>
    /// Sincroniza apoyos definidos en GH con nodos y restricciones en SAP2000.
    /// </summary>
    public class GH_DefineSupports : GH_Component
    {
        private const double DefaultTolerance = 30.0;
        private readonly Dictionary<string, SupportRecord> _supportRegistry = new();

        public GH_DefineSupports()
            : base("Define Supports", "Supports", "Define apoyos (Fijo, Deslizante, Empotrado) en SAP2000.", "RhinoSAP", "Connection")
        {
        }

        public override Guid ComponentGuid => new Guid("f23a3b4b-4f05-4b1f-8d54-9bd89a1fb4e7");
        protected override System.Drawing.Bitmap Icon => null;

        protected override void RegisterInputParams(GH_InputParamManager pManager)
        {
            pManager.AddPointParameter("Points", "P", "Puntos que representan los apoyos en GH.", GH_ParamAccess.tree);
            pManager.AddTextParameter("Types", "T", "Tipo de apoyo por punto (estructura paralela a Points): Fijo, Deslizante o Empotrado.", GH_ParamAccess.tree);
            pManager.AddGenericParameter("SapModel", "Model", "Referencia al cSapModel activo.", GH_ParamAccess.item);
            pManager.AddNumberParameter("Tolerance", "Tol", "Tolerancia (unidades de Rhino, se convierte a metros en SAP).", GH_ParamAccess.item, DefaultTolerance);
            pManager.AddBooleanParameter("Push", "Push", "Forzar sincronización manual (botón).", GH_ParamAccess.item, false);
        }

        protected override void RegisterOutputParams(GH_OutputParamManager pManager)
        {
            pManager.AddTextParameter("Nodes", "N", "Nombres de los nodos utilizados o creados en SAP2000.", GH_ParamAccess.list);
            pManager.AddTextParameter("Messages", "Msg", "Mensajes descriptivos de la operación.", GH_ParamAccess.list);
            pManager.AddBooleanParameter("Success", "OK", "Indica si la sincronización fue exitosa.", GH_ParamAccess.item);
        }

        protected override void SolveInstance(IGH_DataAccess DA)
        {
            GH_Structure<GH_Point> pointTree;
            DA.GetDataTree(0, out pointTree);
            if (pointTree == null || pointTree.IsEmpty)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Warning, "Debe proporcionar al menos un punto de apoyo.");
                DA.SetDataList(0, Array.Empty<string>());
                DA.SetDataList(1, new[] { "Sin puntos de entrada." });
                DA.SetData(2, false);
                return;
            }

            GH_Structure<GH_String> typesTree;
            DA.GetDataTree(1, out typesTree);

            object modelObj = null;
            if (!DA.GetData(2, ref modelObj) || modelObj == null)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "Debe proporcionar un cSapModel válido.");
                DA.SetDataList(0, Array.Empty<string>());
                DA.SetDataList(1, new[] { "Referencia a SapModel inválida." });
                DA.SetData(2, false);
                return;
            }

            var sapModel = ExtractSapModel(modelObj);
            if (sapModel == null)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "No se pudo convertir el objeto proporcionado a cSapModel.");
                DA.SetDataList(0, Array.Empty<string>());
                DA.SetDataList(1, new[] { "Conversión de SapModel fallida." });
                DA.SetData(2, false);
                return;
            }

            double toleranceInput = DefaultTolerance;
            DA.GetData(3, ref toleranceInput);
            toleranceInput = Math.Max(0.0, toleranceInput);
            double tolerance = UnitConversion.ToSapLength(toleranceInput);

            // Leer botón de push (se usa como trigger manual; el componente igual se ejecuta en cada solve).
            bool push = false;
            DA.GetData(4, ref push);

            var messages = new List<string>();
            var snapshots = BuildSnapshots(pointTree, typesTree, messages);
            if (snapshots.Count == 0)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Warning, "No se generaron apoyos válidos para sincronizar.");
                DA.SetDataList(0, Array.Empty<string>());
                DA.SetDataList(1, messages);
                DA.SetData(2, false);
                return;
            }

            var existingNodes = LoadExistingNodes(sapModel);
            CleanupRemovedSupports(sapModel, existingNodes, snapshots.Select(s => s.Id).ToHashSet(), messages);
            var outputNodes = new List<string>();
            bool success = true;
            int createdCount = 0;
            int reusedCount = 0;

            foreach (var snapshot in snapshots)
            {
                var resolveResult = ResolveSupportNode(sapModel, existingNodes, snapshot, tolerance, messages);
                if (!resolveResult.Success || string.IsNullOrEmpty(resolveResult.NodeName))
                {
                    messages.Add(resolveResult.Error);
                    success = false;
                    continue;
                }

                var restraintsCopy = (bool[])snapshot.Restraints.Clone();
                var setRet = sapModel.PointObj.SetRestraint(resolveResult.NodeName, ref restraintsCopy);
                if (setRet != 0)
                {
                    messages.Add($"[ERROR] No se pudo asignar restricción a '{resolveResult.NodeName}' (Código {setRet}).");
                    success = false;
                    continue;
                }

                _supportRegistry[snapshot.Id] = new SupportRecord
                {
                    NodeName = resolveResult.NodeName,
                    Position = snapshot.Point,
                    Owned = resolveResult.Created
                };

                if (resolveResult.Created)
                {
                    createdCount++;
                    existingNodes.Add(new NodeRecord(resolveResult.NodeName, snapshot.Point));
                }
                else
                {
                    reusedCount++;
                    UpdateExistingNodePosition(existingNodes, resolveResult.NodeName, snapshot.Point);
                }

                outputNodes.Add(resolveResult.NodeName);
                messages.Add($"[INFO] Nodo '{resolveResult.NodeName}' → apoyo {snapshot.NormalizedType}.");
            }

            messages.Add($"[INFO] Nodos nuevos: {createdCount}. Nodos reutilizados: {reusedCount}.");

            DA.SetDataList(0, outputNodes);
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

        private static List<NodeRecord> LoadExistingNodes(cSapModel sapModel)
        {
            var nodes = new List<NodeRecord>();
            int number = 0;
            string[] names = Array.Empty<string>();
            int ret = sapModel.PointObj.GetNameList(ref number, ref names);
            if (ret != 0 || number == 0 || names == null)
                return nodes;

            foreach (var name in names)
            {
                double x = 0, y = 0, z = 0;
                if (sapModel.PointObj.GetCoordCartesian(name, ref x, ref y, ref z) == 0)
                {
                    nodes.Add(new NodeRecord(name, new Point3d(x, y, z)));
                }
            }

            return nodes;
        }

        private static void UpdateExistingNodePosition(List<NodeRecord> nodes, string nodeName, Point3d newPosition)
        {
            var record = nodes.FirstOrDefault(n => string.Equals(n.Name, nodeName, StringComparison.OrdinalIgnoreCase));
            if (record == null)
                return;

            nodes.Remove(record);
            nodes.Add(new NodeRecord(nodeName, newPosition));
        }

        private static void RemoveNodeFromCache(List<NodeRecord> nodes, string nodeName)
        {
            var record = nodes.FirstOrDefault(n => string.Equals(n.Name, nodeName, StringComparison.OrdinalIgnoreCase));
            if (record != null)
            {
                nodes.Remove(record);
            }
        }

        private static string BuildSnapshotId(GH_Path path, int index, GH_Point ghPoint)
        {
            if (ghPoint != null && ghPoint.ReferenceID != Guid.Empty)
            {
                return ghPoint.ReferenceID.ToString();
            }

            return $"{path}:{index}";
        }

        private bool DeleteOwnedNode(cSapModel sapModel, string nodeName, List<NodeRecord> existingNodes, List<string> messages)
        {
            if (string.IsNullOrWhiteSpace(nodeName))
                return false;

            int restraintRet = sapModel.PointObj.DeleteRestraint(nodeName);
            if (restraintRet != 0)
            {
                messages?.Add($"[WARN] No se pudo limpiar la restricción de '{nodeName}' (Código {restraintRet}).");
            }

            int specialRet = sapModel.PointObj.SetSpecialPoint(nodeName, true);
            if (specialRet != 0)
            {
                messages?.Add($"[WARN] No se pudo marcar '{nodeName}' como punto especial (Código {specialRet}).");
            }

            int deleteRet = sapModel.PointObj.DeleteSpecialPoint(nodeName);
            if (deleteRet == 0)
            {
                RemoveNodeFromCache(existingNodes, nodeName);
                messages?.Add($"[INFO] Nodo '{nodeName}' eliminado (no se requiere más).");
                return true;
            }

            messages?.Add($"[WARN] No se pudo eliminar nodo '{nodeName}' (Código {deleteRet}).");
            return false;
        }

        private SupportNodeResult ResolveSupportNode(
            cSapModel sapModel,
            List<NodeRecord> existingNodes,
            SupportSnapshot snapshot,
            double tolerance,
            List<string> messages)
        {
            double tol2 = tolerance * tolerance;

            if (_supportRegistry.TryGetValue(snapshot.Id, out var existingRecord))
            {
                double delta = existingRecord.Position.DistanceToSquared(snapshot.Point);
                if (delta <= tol2)
                {
                    return new SupportNodeResult(true, existingRecord.NodeName, false);
                }

                if (existingRecord.Owned)
                {
                    bool deleted = DeleteOwnedNode(sapModel, existingRecord.NodeName, existingNodes, messages);
                    if (!deleted)
                    {
                        return new SupportNodeResult(false, string.Empty, false, $"[ERROR] No se pudo eliminar nodo '{existingRecord.NodeName}'.");
                    }
                    _supportRegistry.Remove(snapshot.Id);
                }
                else
                {
                    var freeRet = sapModel.PointObj.DeleteRestraint(existingRecord.NodeName);
                    if (freeRet != 0)
                    {
                        messages.Add($"[WARN] No se pudo limpiar la restricción de '{existingRecord.NodeName}' (Código {freeRet}).");
                    }
                }
            }

            var resolved = FindOrCreateNode(sapModel, existingNodes, snapshot.Point, tolerance);
            if (!resolved.Success || string.IsNullOrEmpty(resolved.NodeName))
                return new SupportNodeResult(false, string.Empty, false, resolved.ErrorMessage);

            return new SupportNodeResult(true, resolved.NodeName, resolved.Created);
        }

        private List<SupportSnapshot> BuildSnapshots(GH_Structure<GH_Point> pointTree, GH_Structure<GH_String> typesTree, List<string> messages)
        {
            var result = new List<SupportSnapshot>();
            if (pointTree == null)
                return result;

            int flatIndex = 0;
            foreach (var path in pointTree.Paths)
            {
                var branch = pointTree.get_Branch(path);
                var typeBranch = typesTree?.get_Branch(path);
                if (branch == null)
                    continue;

                if (typeBranch == null || typeBranch.Count != branch.Count)
                {
                    messages.Add($"[ERROR] Tipos desalineados en rama {path}: se esperaban {branch.Count}, se obtuvieron {(typeBranch == null ? 0 : typeBranch.Count)}.");
                    continue;
                }

                for (int i = 0; i < branch.Count; i++, flatIndex++)
                {
                    if (!(branch[i] is GH_Point ghPoint) || !ghPoint.IsValid)
                    {
                        messages.Add($"[WARN] Punto inválido en rama {path} índice {i}.");
                        continue;
                    }

                    var label = typeBranch[i] is GH_String gs ? gs.Value : typeBranch[i]?.ToString();
                    if (!TryGetRestraints(label ?? string.Empty, out var restraints, out var normalized, out var error))
                    {
                        messages.Add($"{error} (rama {path}, índice {i}).");
                        continue;
                    }

                    string id = BuildSnapshotId(path, i, ghPoint);
                    var sapPoint = UnitConversion.ToSap(ghPoint.Value);
                    result.Add(new SupportSnapshot(id, sapPoint, restraints, normalized));
                }
            }

            return result;
        }

        private void CleanupRemovedSupports(
            cSapModel sapModel,
            List<NodeRecord> existingNodes,
            HashSet<string> activeIds,
            List<string> messages)
        {
            var toRemove = _supportRegistry.Keys.Where(k => !activeIds.Contains(k)).ToList();
            foreach (var id in toRemove)
            {
                var record = _supportRegistry[id];
                if (!string.IsNullOrWhiteSpace(record.NodeName))
                {
                    if (record.Owned)
                    {
                        DeleteOwnedNode(sapModel, record.NodeName, existingNodes, messages);
                    }
                    else
                    {
                        var ret = sapModel.PointObj.DeleteRestraint(record.NodeName);
                        if (ret == 0)
                        {
                            messages.Add($"[INFO] Restricciones removidas de '{record.NodeName}'.");
                        }
                        else
                        {
                            messages.Add($"[WARN] No se pudo remover restricción de '{record.NodeName}' (Código {ret}).");
                        }
                    }
                }
                _supportRegistry.Remove(id);
            }
        }

        private static NodeMatchResult FindOrCreateNode(cSapModel sapModel, List<NodeRecord> existingNodes, Point3d target, double tolerance)
        {
            double tol2 = tolerance * tolerance;
            foreach (var node in existingNodes)
            {
                if (node.Position.DistanceToSquared(target) <= tol2)
                {
                    return new NodeMatchResult(node.Name, false);
                }
            }

            string newName = string.Empty;
            int ret = sapModel.PointObj.AddCartesian(target.X, target.Y, target.Z, ref newName);
            if (ret != 0 || string.IsNullOrEmpty(newName))
            {
                return new NodeMatchResult(string.Empty, false, $"[ERROR] SAP2000 retornó {ret} al crear el nodo.");
            }

            existingNodes.Add(new NodeRecord(newName, target));
            return new NodeMatchResult(newName, true);
        }

        private static bool TryGetRestraints(string typeLabel, out bool[] restraints, out string normalizedLabel, out string error)
        {
            restraints = Array.Empty<bool>();
            normalizedLabel = string.Empty;
            error = string.Empty;

            if (string.IsNullOrWhiteSpace(typeLabel))
            {
                error = "[ERROR] Tipo de apoyo vacío.";
                return false;
            }

            string normalized = typeLabel.Trim().ToLowerInvariant();
            switch (normalized)
            {
                case "fijo":
                    restraints = new[] { true, false, true, false, false, false };
                    normalizedLabel = "Fijo";
                    return true;
                case "deslizante":
                    restraints = new[] { false, false, true, false, false, false };
                    normalizedLabel = "Deslizante";
                    return true;
                case "empotrado":
                    restraints = new[] { true, false, true, false, true, false };
                    normalizedLabel = "Empotrado";
                    return true;
                default:
                    error = $"[ERROR] Tipo de apoyo '{typeLabel}' no reconocido. Use Fijo, Deslizante o Empotrado.";
                    return false;
            }
        }

        private class SupportRecord
        {
            public string NodeName { get; set; } = string.Empty;
            public Point3d Position { get; set; }
            public bool Owned { get; set; }
        }

        private class SupportSnapshot
        {
            public SupportSnapshot(string id, Point3d point, bool[] restraints, string normalizedType)
            {
                Id = id;
                Point = point;
                Restraints = restraints;
                NormalizedType = normalizedType;
            }

            public string Id { get; }
            public Point3d Point { get; }
            public bool[] Restraints { get; }
            public string NormalizedType { get; }
        }

        private class NodeRecord
        {
            public NodeRecord(string name, Point3d position)
            {
                Name = name;
                Position = position;
            }

            public string Name { get; }
            public Point3d Position { get; }
        }

        private class NodeMatchResult
        {
            public NodeMatchResult(string nodeName, bool created, string error = "")
            {
                NodeName = nodeName;
                Created = created;
                ErrorMessage = error ?? string.Empty;
            }

            public string NodeName { get; }
            public bool Created { get; }
            public bool Success => !string.IsNullOrEmpty(NodeName);
            public string ErrorMessage { get; }
        }

        private class SupportNodeResult
        {
            public SupportNodeResult(bool success, string nodeName, bool created, string error = "")
            {
                Success = success;
                NodeName = nodeName;
                Created = created;
                Error = error;
            }

            public bool Success { get; }
            public string NodeName { get; }
            public bool Created { get; }
            public string Error { get; }
        }
    }
}
