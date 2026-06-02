using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Types;

namespace RhinoSAP.Grasshopper
{
    /// <summary>
    /// Verifica elementos de madera en tracción paralela (NCh1198:2024) usando resultados de SAP.
    /// </summary>
    public class EW_Check_TensionParallel : GH_Component
    {
        private const double Kh = 0.85;   // Factor por humedad (fijo para este requerimiento)
        private const double Kct = 0.60;  // Factor por concentración de tensiones

        // Tabla mínima de propiedades admisibles (MPa) para materiales soportados.
        private static readonly Dictionary<string, double> FtpByMaterial = new(StringComparer.OrdinalIgnoreCase)
        {
            { "MGP10", 4.0 }
        };

        public EW_Check_TensionParallel()
            : base("EW_Check_TensionParallel", "EW_Ft",
                  "Verifica tracción paralela a la fibra según NCh1198:2024 para secciones MGP.",
                  "RhinoSAP", "Checks")
        {
        }

        public override Guid ComponentGuid => new Guid("C5AE605E-1870-4F4F-9E1C-30EC6013CE37");
        protected override System.Drawing.Bitmap Icon => null;

        protected override void RegisterInputParams(GH_InputParamManager pManager)
        {
            pManager.AddGenericParameter("Forces", "F", "Resultados por elemento/combos (tree). Se acepta FrameForceResult o string '... | Combo: X | P=...'.", GH_ParamAccess.tree);
            pManager.AddTextParameter("Sections", "Sec", "Sección por rama (p.ej. MGP10_33x73) en paralelo a las ramas de Forces.", GH_ParamAccess.tree);
        }

        protected override void RegisterOutputParams(GH_OutputParamManager pManager)
        {
            pManager.AddNumberParameter("ft", "ft", "Tensión de trabajo por combo (MPa).", GH_ParamAccess.tree);
            pManager.AddNumberParameter("Ft_adm", "Ft,adm", "Tensión admisible de diseño (MPa) por elemento.", GH_ParamAccess.list);
            pManager.AddNumberParameter("Util", "Util", "Utilización ft / Ft_adm por combo.", GH_ParamAccess.tree);
            pManager.AddBooleanParameter("OK", "OK", "Cumple (true) por combo.", GH_ParamAccess.tree);
            pManager.AddTextParameter("CriticalCombo", "Crit", "Combinación más desfavorable por elemento.", GH_ParamAccess.list);
            pManager.AddTextParameter("ControlForce", "Ctrl", "Fuerza utilizada para el cálculo (P) por elemento.", GH_ParamAccess.list);
            pManager.AddTextParameter("Verif", "Verif", "Detalle de cálculo (memoria) por elemento.", GH_ParamAccess.list);
            pManager.AddTextParameter("Messages", "Msg", "Mensajes de verificación.", GH_ParamAccess.list);
        }

        protected override void SolveInstance(IGH_DataAccess DA)
        {
            var forcesTree = new GH_Structure<IGH_Goo>();
            if (!DA.GetDataTree(0, out forcesTree))
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "No se pudo leer Forces.");
                return;
            }

            var sectionTree = new GH_Structure<GH_String>();
            if (!DA.GetDataTree(1, out sectionTree) || sectionTree.Branches.Count == 0)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "Secciones vacías.");
                return;
            }

            var ftTree = new GH_Structure<GH_Number>();
            var utilTree = new GH_Structure<GH_Number>();
            var okTree = new GH_Structure<GH_Boolean>();
            var critical = new List<string>();
            var ftAdmList = new List<double>();
            var controlList = new List<string>();
            var verifList = new List<string>();
            var messages = new List<string>();

            int branchCount = forcesTree.Branches.Count;
            int sectionBranchCount = sectionTree.Branches.Count;
            if (branchCount != sectionBranchCount)
            {
                messages.Add($"[WARN] Branches en Forces ({branchCount}) ≠ secciones ({sectionBranchCount}). Se usa el mínimo común.");
            }

            int elementCount = Math.Min(branchCount, sectionBranchCount);
            for (int i = 0; i < elementCount; i++)
            {
                var branchPath = forcesTree.Paths[i];
                var branch = forcesTree.Branches[i];
                string section = GetSectionName(sectionTree, i, messages);

                if (!TryParseSection(section, out var material, out double b, out double h, messages))
                {
                    critical.Add("Sección inválida");
                    ftAdmList.Add(0);
                    continue;
                }

                if (!FtpByMaterial.TryGetValue(material, out double Ftp))
                {
                    messages.Add($"[ERROR] Material '{material}' no soportado.");
                    critical.Add("Material no soportado");
                    ftAdmList.Add(0);
                    continue;
                }

                double area = b * h; // mm2
                double an = Math.Max(area, 0.75 * area);
                double FtAdm = Math.Round(Ftp * Kh * 1.0 * 1.0 * Kct, 2); // MPa
                ftAdmList.Add(FtAdm);

                double worstUtil = double.MinValue;
                string worstCombo = "N/A";
                double worstP = 0.0;
                double worstFt = 0.0;

                for (int j = 0; j < branch.Count; j++)
                {
                    var info = ParseForce(branch[j], messages);
                    if (info == null)
                        continue;

                    double ft = 0.0;
                    double util = 0.0;
                    bool ok = true;

                    if (info.P > 0) // Solo tracción
                    {
                        ft = (info.P * 1000.0) / an; // kN -> N, /mm2 => MPa
                        util = FtAdm > 0 ? ft / FtAdm : 0.0;
                        ok = util <= 1.0 + 1e-9;
                    }

                    ftTree.Append(new GH_Number(Math.Round(ft, 2)), branchPath);
                    utilTree.Append(new GH_Number(Math.Round(util, 2)), branchPath);
                    okTree.Append(new GH_Boolean(ok), branchPath);

                    if (util > worstUtil)
                    {
                        worstUtil = util;
                        worstCombo = info.Combo ?? $"idx{j}";
                        worstP = info.P;
                        worstFt = ft;
                    }
                }

                if (worstUtil < 0)
                {
                    worstUtil = 0;
                    worstCombo = "Sin tracción (P<=0)";
                    worstP = 0.0;
                    worstFt = 0.0;
                }

                critical.Add($"{section} -> {worstCombo} (util={Math.Round(worstUtil, 2)})");
                controlList.Add($"{section} | Combo: {worstCombo} | P={Math.Round(worstP, 2)}");
                verifList.Add(
                    $"Sección: {section} | Mat: {material} | b={b} mm, h={h} mm, A={Math.Round(area, 4)} mm2, An={Math.Round(an, 4)} mm2 | " +
                    $"Ftp={Ftp} MPa, Kh={Kh}, Kct={Kct} => Ft,adm = Ftp*Kh*Kct = {Math.Round(FtAdm, 2)} MPa | " +
                    $"Combo crítico: {worstCombo} | P = {Math.Round(worstP, 2)} kN | " +
                    $"ft = P*1000/An = {Math.Round(worstP, 2)}*1000/{Math.Round(an, 4)} = {Math.Round(worstFt, 2)} MPa | " +
                    $"util = ft/Ft,adm = {Math.Round(worstFt, 2)}/{Math.Round(FtAdm, 2)} = {Math.Round(worstUtil, 2)} | " +
                    $"OK = { (worstUtil <= 1.0 + 1e-9 ? "✔" : "✖") }");
            }

            DA.SetDataTree(0, ftTree);
            DA.SetDataList(1, ftAdmList);
            DA.SetDataTree(2, utilTree);
            DA.SetDataTree(3, okTree);
            DA.SetDataList(4, critical);
            DA.SetDataList(5, controlList);
            DA.SetDataList(6, verifList);
            DA.SetDataList(7, messages);
        }

        private bool TryParseSection(string section, out string material, out double b, out double h, List<string> messages)
        {
            material = string.Empty;
            b = h = 0;

            if (string.IsNullOrWhiteSpace(section) || !section.Contains("_") || !section.Contains("x"))
            {
                messages.Add($"[ERROR] Formato de sección inválido: '{section}'. Esperado MGP10_33x73.");
                return false;
            }

            try
            {
                var parts = section.Split('_');
                material = parts[0].Trim();
                var dims = parts[1].Split('x');
                b = double.Parse(dims[0], CultureInfo.InvariantCulture);
                h = double.Parse(dims[1], CultureInfo.InvariantCulture);
                return true;
            }
            catch
            {
                messages.Add($"[ERROR] No se pudieron parsear dimensiones en '{section}'.");
                return false;
            }
        }

        private ForceInfo ParseForce(IGH_Goo goo, List<string> messages)
        {
            if (goo == null) return null;

            if (goo is GH_ObjectWrapper wrap)
            {
                if (wrap.Value is FrameForceResult fr)
                {
                    return new ForceInfo
                    {
                        Combo = fr.ComboReported ?? fr.RequestedCombo,
                        P = fr.P
                    };
                }
                if (wrap.Value is string s1)
                    return ParseForceString(s1, messages);
            }

            if (goo is GH_String gs)
                return ParseForceString(gs.Value, messages);

            return null;
        }

        private ForceInfo ParseForceString(string text, List<string> messages)
        {
            if (string.IsNullOrWhiteSpace(text)) return null;

            // Ejemplo: "53 | Combo: D | P=0.37, M3=-43564.79"
            try
            {
                string combo = "N/A";
                double pVal = 0.0;

                int comboIdx = text.IndexOf("Combo:", StringComparison.OrdinalIgnoreCase);
                if (comboIdx >= 0)
                {
                    int pipe = text.IndexOf('|', comboIdx);
                    combo = pipe > comboIdx
                        ? text.Substring(comboIdx + 6, pipe - (comboIdx + 6)).Trim().Trim(':')
                        : text.Substring(comboIdx + 6).Trim().Trim(':');
                }

                int pIdx = text.IndexOf("P=", StringComparison.OrdinalIgnoreCase);
                if (pIdx >= 0)
                {
                    int sep = text.IndexOf(',', pIdx);
                    string pStr = sep > pIdx ? text.Substring(pIdx + 2, sep - (pIdx + 2)) : text.Substring(pIdx + 2);
                    double.TryParse(pStr, NumberStyles.Any, CultureInfo.InvariantCulture, out pVal);
                }

                return new ForceInfo { Combo = combo, P = pVal };
            }
            catch (Exception ex)
            {
                messages.Add($"[WARN] No se pudo parsear fuerza desde texto: '{text}'. Detalle: {ex.Message}");
                return null;
            }
        }

        private class ForceInfo
        {
            public string Combo { get; set; }
            public double P { get; set; } // kN
        }

        private string GetSectionName(GH_Structure<GH_String> sectionTree, int index, List<string> messages)
        {
            if (sectionTree == null || index >= sectionTree.Branches.Count)
            {
                messages.Add($"[ERROR] No existe rama de sección para índice {index}.");
                return string.Empty;
            }

            var branch = sectionTree.Branches[index];
            if (branch == null || branch.Count == 0)
            {
                messages.Add($"[ERROR] Rama de sección vacía en índice {index}.");
                return string.Empty;
            }

            var val = branch[0];
            if (val is GH_String gs) return gs.Value;

            messages.Add($"[WARN] Tipo de sección no reconocido en índice {index}; se espera GH_String.");
            return val?.ToString() ?? string.Empty;
        }
    }
}

