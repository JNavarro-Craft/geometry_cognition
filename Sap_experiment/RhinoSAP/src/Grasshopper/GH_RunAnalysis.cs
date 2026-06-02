using System;
using System.Collections.Generic;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Types;
using SAP2000v1;

namespace RhinoSAP.Grasshopper
{
    /// <summary>
    /// Ejecuta el análisis estructural en SAP2000 y recupera las solicitaciones por frame/combinación.
    /// </summary>
    public class GH_RunAnalysis : GH_Component
    {
        private bool _lastRunState;
        private GH_Structure<GH_ObjectWrapper> _lastResults = new();
        private GH_Structure<GH_String> _lastMaxForces = new();
        private List<string> _lastSections = new();
        private List<double> _lastLengths = new();
        private List<double> _lastKp = new();
        private List<string> _lastMessages = new();
        private bool _lastSuccess;

            private static readonly string[] ComboOrder =
            {
                "D",
                "D+L",
                "D+W",
                "D+0,75L+0,75W+0,75S",
                "0,6D+W",
                "D+S",
                "D+0,75L+0,75S",
                "ENVOLVENTE"
            };

        public GH_RunAnalysis()
            : base("Run Analysis", "RunSAP",
                  "Ejecuta el análisis en SAP2000 y devuelve solicitaciones por frame/combo.",
                  "RhinoSAP", "Connection")
        {
        }

        public override Guid ComponentGuid => new Guid("4E6CF8B4-9ED4-4E15-9D88-4F72AFD8639E");
        protected override System.Drawing.Bitmap Icon => null;

        protected override void RegisterInputParams(GH_InputParamManager pManager)
        {
            pManager.AddGenericParameter("SapModel", "Model", "Instancia cSapModel ya inicializada.", GH_ParamAccess.item);
            pManager.AddTextParameter("Frames", "Frames", "Lista ordenada de nombres de FrameObj a consultar.", GH_ParamAccess.list);
            pManager.AddBooleanParameter("Run", "Run", "Trigger para ejecutar el análisis y lectura de resultados.", GH_ParamAccess.item, false);
        }

        protected override void RegisterOutputParams(GH_OutputParamManager pManager)
        {
            pManager.AddGenericParameter("Forces", "Forces", "Solicitaciones por frame/combo en un DataTree.", GH_ParamAccess.tree);
            pManager.AddTextParameter("MaxForces", "MaxF", "Máximos |P| y |M3| por frame y combinación (orden fijo).", GH_ParamAccess.tree);
            pManager.AddTextParameter("Sections", "Sec", "Sección asignada a cada frame en el mismo orden de entrada.", GH_ParamAccess.list);
            pManager.AddNumberParameter("Lengths", "Len", "Length of each frame in mm, same indexing as Forces and Sections.", GH_ParamAccess.list);
            pManager.AddNumberParameter("Kp", "Kp", "Factor de longitud efectiva por elemento (1.0 o 2.5).", GH_ParamAccess.list);
            pManager.AddTextParameter("Messages", "Msg", "Mensajes de depuración.", GH_ParamAccess.list);
            pManager.AddBooleanParameter("Success", "OK", "Verdadero si el análisis se ejecutó sin errores.", GH_ParamAccess.item);
        }

        protected override void SolveInstance(IGH_DataAccess DA)
        {
            object sapModelObj = null;
            if (!DA.GetData(0, ref sapModelObj) || sapModelObj == null)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "SapModel inválido.");
                OutputCachedState(DA, "[ERROR] SapModel inválido.");
                return;
            }

            var frameNames = new List<string>();
            if (!DA.GetDataList(1, frameNames) || frameNames.Count == 0)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "Lista de frames vacía.");
                OutputCachedState(DA, "[ERROR] Lista de frames vacía.");
                return;
            }

            bool run = false;
            DA.GetData(2, ref run);

            var sapModel = ExtractSapModel(sapModelObj);
            if (sapModel == null)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "No se pudo convertir SapModel.");
                OutputCachedState(DA, "[ERROR] Conversión SapModel fallida.");
                return;
            }

            bool shouldExecute = run && !_lastRunState;
            _lastRunState = run;

            if (!shouldExecute)
            {
                var passiveMessages = new List<string>(_lastMessages);
                passiveMessages.Add(run
                    ? "[INFO] Run permanece en true. Libere y vuelva a pulsar para reejecutar."
                    : "[INFO] Run = false. En espera de activación.");
                DA.SetDataTree(0, _lastResults ?? new GH_Structure<GH_ObjectWrapper>());
                DA.SetDataTree(1, _lastMaxForces ?? new GH_Structure<GH_String>());
                DA.SetDataList(2, _lastSections ?? new List<string>());
                DA.SetDataList(3, _lastLengths ?? new List<double>());
                DA.SetDataList(4, _lastKp ?? new List<double>());
                DA.SetDataList(5, passiveMessages);
                DA.SetData(6, _lastSuccess);
                return;
            }

            var messages = new List<string>();
            var resultTree = new GH_Structure<GH_ObjectWrapper>();
            var maxTree = new GH_Structure<GH_String>();
            var sections = new List<string>();
            var lengths = new List<double>();
            var kpFactors = new List<double>();
            bool success = true;
            var unitScale = ComputeUnitFactors(sapModel, messages);

            try
            {
                int runRet = sapModel.Analyze.RunAnalysis();
                if (runRet != 0)
                {
                    success = false;
                    messages.Add($"[ERROR] RunAnalysis retornó código {runRet}.");
                    Finalize(DA, resultTree, maxTree, sections, lengths, kpFactors, messages, success);
                    return;
                }
                messages.Add("[INFO] RunAnalysis completado.");

                int comboCount = 0;
                string[] combos = Array.Empty<string>();
                int comboRet = sapModel.RespCombo.GetNameList(ref comboCount, ref combos);
                if (comboRet != 0 || comboCount == 0 || combos == null || combos.Length == 0)
                {
                    success = false;
                    messages.Add(comboRet != 0
                        ? $"[ERROR] GetNameList retornó {comboRet}."
                        : "[ERROR] No existen combinaciones de carga en el modelo.");
                    Finalize(DA, resultTree, maxTree, sections, lengths, kpFactors, messages, success);
                    return;
                }
                messages.Add($"[INFO] Se recuperaron {comboCount} combinaciones.");

                for (int frameIndex = 0; frameIndex < frameNames.Count; frameIndex++)
                {
                    string frameName = frameNames[frameIndex];
                    if (string.IsNullOrWhiteSpace(frameName))
                    {
                        messages.Add($"[WARN] Nombre de frame vacío en índice {frameIndex}. Se omite.");
                        continue;
                    }

                    for (int comboIndex = 0; comboIndex < combos.Length; comboIndex++)
                    {
                        string comboName = combos[comboIndex];
                        // Única rama por barra; los combos se diferencian por su nombre en el objeto
                        var path = new GH_Path(frameIndex);

                        // Seleccionar solo este combo para lectura
                        DeselectAllForcesSelection(sapModel, messages);
                        int selRet = sapModel.Results.Setup.SetComboSelectedForOutput(comboName);
                        if (selRet != 0)
                        {
                            messages.Add($"[WARN] No se pudo activar combo '{comboName}' para lectura (ret={selRet}).");
                            continue;
                        }

                        var forceResults = GetFrameForces(sapModel, frameName, comboName, unitScale, messages);

                        if (forceResults == null)
                        {
                            success = false;
                            continue;
                        }

                        foreach (var fr in forceResults)
                        {
                            resultTree.Append(new GH_ObjectWrapper(fr), path);
                        }

                        if (forceResults.Count == 0)
                        {
                            messages.Add($"[WARN] Sin resultados para frame '{frameName}' combo '{comboName}'.");
                        }
                    }
                }

                // Calcular máximos por frame/combos definidos en ComboOrder
                ComputeMaxForces(resultTree, frameNames, combos, maxTree, messages);

                // Obtener secciones por frame en el mismo orden
                sections = GetSectionsForFrames(sapModel, frameNames, messages);
                lengths = GetLengthsForFrames(sapModel, frameNames, unitScale, messages);
                kpFactors = GetKpForFrames(sapModel, frameNames, messages);

                messages.Add($"[INFO] Se capturaron {resultTree.DataCount} resultados.");
            }
            catch (Exception ex)
            {
                success = false;
                messages.Add($"[ERROR] Excepción: {ex.Message}");
            }

            Finalize(DA, resultTree, maxTree, sections, lengths, kpFactors, messages, success);
        }

        private void Finalize(IGH_DataAccess DA, GH_Structure<GH_ObjectWrapper> tree, GH_Structure<GH_String> maxTree, List<string> sections, List<double> lengths, List<double> kpFactors, List<string> messages, bool success)
        {
            _lastResults = tree ?? new GH_Structure<GH_ObjectWrapper>();
            _lastMaxForces = maxTree ?? new GH_Structure<GH_String>();
            _lastSections = sections ?? new List<string>();
            _lastLengths = lengths ?? new List<double>();
            _lastKp = kpFactors ?? new List<double>();
            _lastMessages = messages ?? new List<string>();
            _lastSuccess = success;

            DA.SetDataTree(0, _lastResults);
            DA.SetDataTree(1, _lastMaxForces);
            DA.SetDataList(2, _lastSections);
            DA.SetDataList(3, _lastLengths);
            DA.SetDataList(4, _lastKp);
            DA.SetDataList(5, _lastMessages);
            DA.SetData(6, success);
        }

        private void OutputCachedState(IGH_DataAccess DA, string extraMessage)
        {
            var messages = new List<string>(_lastMessages);
            if (!string.IsNullOrEmpty(extraMessage))
            {
                messages.Add(extraMessage);
            }

            DA.SetDataTree(0, _lastResults ?? new GH_Structure<GH_ObjectWrapper>());
            DA.SetDataTree(1, _lastMaxForces ?? new GH_Structure<GH_String>());
            DA.SetDataList(2, _lastSections ?? new List<string>());
            DA.SetDataList(3, _lastLengths ?? new List<double>());
            DA.SetDataList(4, _lastKp ?? new List<double>());
            DA.SetDataList(5, messages);
            DA.SetData(6, _lastSuccess);
        }

        private static cSapModel ExtractSapModel(object obj)
        {
            if (obj is cSapModel direct)
                return direct;

            if (obj is GH_ObjectWrapper wrapper && wrapper.Value is cSapModel wrapped)
                return wrapped;

            return null;
        }

        private List<FrameForceResult> GetFrameForces(cSapModel sapModel, string frameName, string comboName, UnitScale scale, List<string> messages)
        {
            int numberResults = 0;
            string[] obj = Array.Empty<string>();
            double[] objSta = Array.Empty<double>();
            string[] elem = Array.Empty<string>();
            double[] elemSta = Array.Empty<double>();
            string[] loadCase = Array.Empty<string>();
            string[] stepType = Array.Empty<string>();
            double[] stepNum = Array.Empty<double>();
            double[] p = Array.Empty<double>();
            double[] v2 = Array.Empty<double>();
            double[] v3 = Array.Empty<double>();
            double[] t = Array.Empty<double>();
            double[] m2 = Array.Empty<double>();
            double[] m3 = Array.Empty<double>();

            int ret = sapModel.Results.FrameForce(
                frameName,
                eItemTypeElm.ObjectElm,
                ref numberResults,
                ref obj,
                ref objSta,
                ref elem,
                ref elemSta,
                ref loadCase,
                ref stepType,
                ref stepNum,
                ref p,
                ref v2,
                ref v3,
                ref t,
                ref m2,
                ref m3);

            if (ret != 0)
            {
                messages.Add($"[ERROR] GetFrameForce falló para '{frameName}' en combo '{comboName}' (ret={ret}).");
                return null;
            }

            var results = new List<FrameForceResult>(numberResults);
            for (int i = 0; i < numberResults; i++)
            {
                // Filtrar estrictamente por combo solicitado para evitar duplicados cuando SAP devuelve selección ampliada/envolventes.
                string reportedCase = loadCase != null && loadCase.Length > i ? loadCase[i] : comboName;
                if (!string.Equals(reportedCase, comboName, StringComparison.OrdinalIgnoreCase))
                    continue;

                var record = new FrameForceResult
                (
                    frameName,
                    comboName,
                    reportedCase,
                    elemSta != null && elemSta.Length > i ? elemSta[i] : 0.0,
                    GetValue(p, i) * scale.ForceToKn, // P en kN
                    GetValue(v2, i),
                    GetValue(v3, i),
                    GetValue(t, i),
                    GetValue(m2, i),
                    GetValue(m3, i) * scale.MomentToNmm // M3 en N*mm
                );
                results.Add(record);
            }

            return results;
        }

        private static double GetValue(double[] array, int index)
        {
            if (array == null || index < 0 || index >= array.Length)
                return 0.0;
            return array[index];
        }

        private class UnitScale
        {
            public double ForceToKn { get; set; } = 1.0;      // Escala de fuerza hacia kN
            public double MomentToNmm { get; set; } = 1.0;    // Escala de momento hacia N*mm
            public double LengthToMm { get; set; } = 1.0;     // Escala de longitud hacia mm
            public string SourceUnits { get; set; } = "Unknown";
        }

        private UnitScale ComputeUnitFactors(cSapModel sapModel, List<string> messages)
        {
            var scale = new UnitScale
            {
                ForceToKn = 1.0,
                MomentToNmm = 1.0,
                LengthToMm = 1.0,
                SourceUnits = "Unknown"
            };

            try
            {
                var unitsEnum = sapModel.GetPresentUnits();
                scale.SourceUnits = unitsEnum.ToString();

                // Mapear unidades comunes a kN y N*mm
                switch (unitsEnum)
                {
                    case eUnits.kgf_m_C:
                        scale.ForceToKn = 0.00980665;          // kgf -> kN
                        scale.MomentToNmm = 9.80665 * 1000.0;  // kgf*m -> N*mm
                        scale.LengthToMm = 1000.0;             // m -> mm
                        break;
                    case eUnits.kgf_mm_C:
                        scale.ForceToKn = 0.00980665;          // kgf -> kN
                        scale.MomentToNmm = 9.80665;           // kgf*mm -> N*mm
                        scale.LengthToMm = 1.0;                // mm -> mm
                        break;
                    case eUnits.N_m_C:
                        scale.ForceToKn = 0.001;               // N -> kN
                        scale.MomentToNmm = 1000.0;            // N*m -> N*mm
                        scale.LengthToMm = 1000.0;             // m -> mm
                        break;
                    case eUnits.N_mm_C:
                        scale.ForceToKn = 0.000001;            // N -> kN
                        scale.MomentToNmm = 1.0;               // N*mm stays
                        scale.LengthToMm = 1.0;                // mm -> mm
                        break;
                    case eUnits.kN_m_C:
                        scale.ForceToKn = 1.0;                 // kN -> kN
                        scale.MomentToNmm = 1000.0 * 1000.0;   // kN*m -> N*mm
                        scale.LengthToMm = 1000.0;             // m -> mm
                        break;
                    case eUnits.kN_mm_C:
                        scale.ForceToKn = 1.0;                 // kN -> kN
                        scale.MomentToNmm = 1000.0;            // kN*mm -> N*mm
                        scale.LengthToMm = 1.0;                // mm -> mm
                        break;
                    default:
                        messages?.Add($"[WARN] Unidades {unitsEnum} no mapeadas; se dejan factores 1.0 (P en unidades de modelo, M3 en unidades de modelo, longitudes en unidades de modelo).");
                        break;
                }

                messages?.Add($"[INFO] Unidades de modelo: {scale.SourceUnits}. P en kN, M3 en N*mm, longitudes en mm.");
            }
            catch (Exception ex)
            {
                messages?.Add($"[WARN] No se pudieron leer las unidades actuales: {ex.Message}. Se asumen factores 1.0.");
            }
            return scale;
        }

        private List<string> GetSectionsForFrames(cSapModel sapModel, IList<string> frameNames, List<string> messages)
        {
            var result = new List<string>();
            if (frameNames == null) return result;

            foreach (var frame in frameNames)
            {
                string sec = string.Empty;
                string auto = string.Empty;
                if (string.IsNullOrWhiteSpace(frame))
                {
                    result.Add(string.Empty);
                    messages?.Add("[WARN] Nombre de frame vacío al leer sección.");
                    continue;
                }

                try
                {
                    int ret = sapModel.FrameObj.GetSection(frame, ref sec, ref auto);
                    if (ret != 0)
                    {
                        messages?.Add($"[WARN] No se pudo obtener sección de '{frame}' (ret={ret}).");
                        result.Add(string.Empty);
                    }
                    else
                    {
                        result.Add(sec ?? string.Empty);
                    }
                }
                catch (Exception ex)
                {
                    messages?.Add($"[WARN] Excepción al leer sección de '{frame}': {ex.Message}");
                    result.Add(string.Empty);
                }
            }

            return result;
        }

        private List<double> GetLengthsForFrames(cSapModel sapModel, IList<string> frameNames, UnitScale scale, List<string> messages)
        {
            var result = new List<double>();
            if (frameNames == null) return result;

            foreach (var frame in frameNames)
            {
                if (string.IsNullOrWhiteSpace(frame))
                {
                    result.Add(0.0);
                    messages?.Add("[WARN] Nombre de frame vacío al leer longitud.");
                    continue;
                }

                try
                {
                    string pointI = string.Empty;
                    string pointJ = string.Empty;
                    int retPts = sapModel.FrameObj.GetPoints(frame, ref pointI, ref pointJ);
                    if (retPts != 0 || string.IsNullOrWhiteSpace(pointI) || string.IsNullOrWhiteSpace(pointJ))
                    {
                        messages?.Add($"[WARN] No se pudieron obtener puntos del frame '{frame}' (ret={retPts}).");
                        result.Add(0.0);
                    }
                    else
                    {
                        double xi = 0, yi = 0, zi = 0;
                        double xj = 0, yj = 0, zj = 0;

                        int retI = sapModel.PointObj.GetCoordCartesian(pointI, ref xi, ref yi, ref zi);
                        int retJ = sapModel.PointObj.GetCoordCartesian(pointJ, ref xj, ref yj, ref zj);

                        if (retI != 0 || retJ != 0)
                        {
                            messages?.Add($"[WARN] No se pudieron obtener coordenadas de '{frame}' (piRet={retI}, pjRet={retJ}).");
                            result.Add(0.0);
                        }
                        else
                        {
                            double length = Math.Sqrt(
                                Math.Pow(xj - xi, 2) +
                                Math.Pow(yj - yi, 2) +
                                Math.Pow(zj - zi, 2));
                            result.Add(length * scale.LengthToMm);
                        }
                    }
                }
                catch (Exception ex)
                {
                    messages?.Add($"[WARN] Excepción al leer longitud de '{frame}': {ex.Message}");
                    result.Add(0.0);
                }
            }

            return result;
        }

        private List<double> GetKpForFrames(cSapModel sapModel, IList<string> frameNames, List<string> messages)
        {
            var kpList = new List<double>();
            if (frameNames == null) return kpList;

            var pointUseCount = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            var framePoints = new List<(string frame, string pi, string pj)>();

            foreach (var frame in frameNames)
            {
                string pi = string.Empty;
                string pj = string.Empty;
                try
                {
                    int ret = sapModel.FrameObj.GetPoints(frame, ref pi, ref pj);
                    if (ret != 0)
                    {
                        messages?.Add($"[WARN] No se pudieron obtener puntos de '{frame}' para Kp (ret={ret}).");
                        framePoints.Add((frame, string.Empty, string.Empty));
                        continue;
                    }
                    framePoints.Add((frame, pi, pj));

                    if (!string.IsNullOrWhiteSpace(pi))
                    {
                        if (!pointUseCount.ContainsKey(pi)) pointUseCount[pi] = 0;
                        pointUseCount[pi]++;
                    }
                    if (!string.IsNullOrWhiteSpace(pj))
                    {
                        if (!pointUseCount.ContainsKey(pj)) pointUseCount[pj] = 0;
                        pointUseCount[pj]++;
                    }
                }
                catch (Exception ex)
                {
                    messages?.Add($"[WARN] Excepción al leer puntos de '{frame}' para Kp: {ex.Message}");
                    framePoints.Add((frame, string.Empty, string.Empty));
                }
            }

            foreach (var fp in framePoints)
            {
                bool nI = fp.pi != null && pointUseCount.TryGetValue(fp.pi, out var cI) && cI > 1;
                bool nJ = fp.pj != null && pointUseCount.TryGetValue(fp.pj, out var cJ) && cJ > 1;
                double kp = (nI && nJ) ? 1.0 : 2.5;
                kpList.Add(kp);
            }

            return kpList;
        }

        private void DeselectAllForcesSelection(cSapModel sapModel, List<string> messages)
        {
            try
            {
                var setup = sapModel?.Results?.Setup;
                if (setup == null) return;

                // Prioridad: método ForOutput si existe
                var miForOutput = setup.GetType().GetMethod("DeselectAllCasesAndCombosForOutput");
                if (miForOutput != null)
                {
                    var retObj = miForOutput.Invoke(setup, null);
                    if (retObj is int ret && ret != 0)
                    {
                        messages?.Add($"[WARN] DeselectAllCasesAndCombosForOutput retornó {ret}.");
                    }
                    return;
                }

                // Fallback: método sin sufijo ForOutput
                var mi = setup.GetType().GetMethod("DeselectAllCasesAndCombos");
                if (mi != null)
                {
                    var retObj = mi.Invoke(setup, null);
                    if (retObj is int ret && ret != 0)
                    {
                        messages?.Add($"[WARN] DeselectAllCasesAndCombos retornó {ret}.");
                    }
                    return;
                }

                // Fallback: métodos separados
                var miCases = setup.GetType().GetMethod("DeselectAllCases");
                var miCombos = setup.GetType().GetMethod("DeselectAllCombos");
                miCases?.Invoke(setup, null);
                miCombos?.Invoke(setup, null);
            }
            catch (Exception ex)
            {
                messages?.Add($"[WARN] No se pudo limpiar selección de resultados: {ex.Message}");
            }
        }

        private void ComputeMaxForces(
            GH_Structure<GH_ObjectWrapper> forces,
            IList<string> frameNames,
            string[] combos,
            GH_Structure<GH_String> maxTree,
            List<string> messages)
        {
            var comboIndexMap = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            if (combos != null)
            {
                for (int i = 0; i < combos.Length; i++)
                {
                    if (!comboIndexMap.ContainsKey(combos[i]))
                        comboIndexMap[combos[i]] = i;
                }
            }

            for (int f = 0; f < frameNames.Count; f++)
            {
                string frame = frameNames[f];
                var path = new GH_Path(f);

                foreach (var comboName in ComboOrder)
                {
                    // Rama única por frame
                    var branchPath = new GH_Path(f);
                    var branch = forces.get_Branch(branchPath);
                    double maxP = 0.0;
                    double maxM3 = 0.0;

                    bool anyMatch = false;
                    if (branch != null)
                    {
                        foreach (var item in branch)
                        {
                            if (item is GH_ObjectWrapper wrapper && wrapper.Value is FrameForceResult fr)
                            {
                                bool comboMatches =
                                    string.Equals(fr.RequestedCombo, comboName, StringComparison.OrdinalIgnoreCase) ||
                                    string.Equals(fr.ComboReported ?? fr.RequestedCombo, comboName, StringComparison.OrdinalIgnoreCase);
                                if (!comboMatches)
                                    continue;

                                anyMatch = true;

                                if (Math.Abs(fr.P) > Math.Abs(maxP)) maxP = fr.P;
                                if (Math.Abs(fr.M3) > Math.Abs(maxM3)) maxM3 = fr.M3;
                            }
                        }
                    }
                    else
                    {
                        messages.Add($"[WARN] No hay rama de resultados para frame '{frame}' combo '{comboName}'.");
                    }

                    if (!anyMatch)
                    {
                        messages.Add($"[WARN] No se encontraron registros para frame '{frame}' combo '{comboName}' al calcular máximos.");
                    }

                    string line = $"{frame} | Combo: {comboName} | P={maxP:F2}, M3={maxM3:F2}";
                    maxTree.Append(new GH_String(line), path);
                }
            }
        }
    }

    /// <summary>
    /// Contenedor ligero para las solicitaciones de un frame.
    /// </summary>
    public class FrameForceResult
    {
        public FrameForceResult(string frame, string requestedCombo, string resultCombo, double station,
            double p, double v2, double v3, double t, double m2, double m3)
        {
            FrameName = frame;
            RequestedCombo = requestedCombo;
            ComboReported = resultCombo;
            Station = station;
            P = p;
            V2 = v2;
            V3 = v3;
            T = t;
            M2 = m2;
            M3 = m3;
        }

        public string FrameName { get; }
        public string RequestedCombo { get; }
        public string ComboReported { get; }
        public double Station { get; }
        public double P { get; }
        public double V2 { get; }
        public double V3 { get; }
        public double T { get; }
        public double M2 { get; }
        public double M3 { get; }

        public override string ToString()
        {
            return $"{FrameName} | Combo: {ComboReported} | S={Station:F3} :: P={P:F2}, V2={V2:F2}, V3={V3:F2}, T={T:F2}, M2={M2:F2}, M3={M3:F2}";
        }
    }
}

