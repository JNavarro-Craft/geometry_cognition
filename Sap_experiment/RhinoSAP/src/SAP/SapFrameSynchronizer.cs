using System;
using System.Collections.Generic;
using System.Linq;
using Rhino.Geometry;
using RhinoSAP.Core;
using SAP2000v1;

namespace RhinoSAP.SAP
{
    /// <summary>
    /// Maneja la sincronización entre curvas GH y barras SAP.
    /// En este modo, la sincronización reconstruye completamente todas las barras.
    /// </summary>
    public class SapFrameSynchronizer
    {
        private readonly Dictionary<string, FrameRecord> _registry;
        private readonly SapLogger _logger;

        public SapFrameSynchronizer(Dictionary<string, FrameRecord> registry, SapLogger logger, double _)
        {
            _registry = registry ?? throw new ArgumentNullException(nameof(registry));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        public IReadOnlyDictionary<string, FrameRecord> Registry => _registry;

        public SyncReport Synchronize(cSapModel sapModel, IList<CurveSnapshot> snapshots, IList<string> sectionNames)
        {
            if (sapModel == null) throw new ArgumentNullException(nameof(sapModel));
            if (snapshots == null) throw new ArgumentNullException(nameof(snapshots));
            if (sectionNames == null) throw new ArgumentNullException(nameof(sectionNames));
            if (snapshots.Count != sectionNames.Count)
            {
                throw new ArgumentException("La lista de secciones debe coincidir con la cantidad de curvas.", nameof(sectionNames));
            }

            var report = new SyncReport();

            // 1. Eliminar todos los frames registrados previamente
            int deleted = 0;
            foreach (var record in _registry.Values.ToList())
            {
                int ret = sapModel.FrameObj.Delete(record.FrameName);
                if (ret == 0)
                {
                    deleted++;
                }
                else
                {
                    report.LogError($"No se pudo eliminar frame '{record.FrameName}' (código {ret}).");
                }
            }
            _registry.Clear();
            report.LogInfo($"Se eliminaron {deleted} frames existentes.");

            // 2. Crear frames nuevos desde los snapshots actuales
            int created = 0;
            for (int i = 0; i < snapshots.Count; i++)
            {
                var snap = snapshots[i];
                if (snap == null || !snap.IsValid)
                {
                    report.LogError("Se ignoró una curva inválida.");
                    continue;
                }

                string proposedName = $"RS_{created + 1:0000}";
                string section = sectionNames[i];
                var result = CreateFrame(sapModel, snap, section, proposedName);
                if (result.Success)
                {
                    _registry[snap.Id] = result.Record;
                    report.Created.Add(result.Record.FrameName);
                    created++;
                }
                else
                {
                    report.LogError($"No se pudo crear frame para curva {snap.Id} (código {result.ErrorCode}).");
                }
            }

            report.LogInfo($"Se crearon {created} frames nuevos a partir de {created} curvas válidas.");

            return report;
        }

        private (bool Success, int ErrorCode, FrameRecord Record) CreateFrame(cSapModel model, CurveSnapshot snap, string sectionName, string proposedName)
        {
            string frameName = proposedName ?? $"RS_{Guid.NewGuid():N}";

            int ret = model.FrameObj.AddByCoord(
                snap.Start.X, snap.Start.Y, snap.Start.Z,
                snap.End.X, snap.End.Y, snap.End.Z,
                ref frameName,
                sectionName ?? string.Empty,
                string.Empty,
                "Global");

            if (ret != 0)
            {
                _logger.Error($"AddByCoord retornó {ret} para curva {snap.Id}");
                return (false, ret, null);
            }

            if (!string.IsNullOrWhiteSpace(sectionName))
            {
                int setSectionRet = model.FrameObj.SetSection(frameName, sectionName);
                if (setSectionRet != 0)
                {
                    _logger.Warn($"SetSection retornó {setSectionRet} para frame '{frameName}'.");
                }
            }

            var record = new FrameRecord
            {
                CurveId = snap.Id,
                FrameName = frameName,
                Start = snap.Start,
                End = snap.End,
                SectionName = sectionName ?? string.Empty
            };

            return (true, 0, record);
        }
    }

    public class CurveSnapshot
    {
        public CurveSnapshot(string id, Point3d start, Point3d end)
        {
            Id = id;
            Start = start;
            End = end;
        }

        public string Id { get; }
        public Point3d Start { get; }
        public Point3d End { get; }
        public bool IsValid => !Start.EpsilonEquals(End, 1e-6);
    }

    public class FrameRecord
    {
        public string CurveId { get; set; }
        public string FrameName { get; set; }
        public Point3d Start { get; set; }
        public Point3d End { get; set; }
        public string SectionName { get; set; }
    }

    public class SyncReport
    {
        public List<string> Created { get; } = new();
        public List<string> Deleted { get; } = new();
        public List<string> Messages { get; } = new();

        public bool Success => !Messages.Any(m => m.StartsWith("[ERROR]", StringComparison.OrdinalIgnoreCase));

        public void LogInfo(string message) => Messages.Add($"[INFO] {message}");
        public void LogError(string message) => Messages.Add($"[ERROR] {message}");
    }
}

