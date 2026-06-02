using System;
using System.Collections.Generic;
using System.Globalization;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Types;

namespace RhinoSAP.Grasshopper
{
    /// <summary>
    /// Verifica compresión paralela a la fibra según NCh1198:2024 con esbeltez y Kp.
    /// </summary>
    public class EW_Check_Compression : GH_Component
    {
        private static readonly Dictionary<string, MaterialProps> MaterialTable = new(StringComparer.OrdinalIgnoreCase)
        {
            // Valores extendidos (ajustar según tabla NCh1198).
            { "MGP10", new MaterialProps(8.4, 10.0, 4.0, 10.0, 10000.0, 1.0) },
            { "MGP12", new MaterialProps(13.5, 15.5, 6.0, 15.5, 12000.0, 1.0) },
            { "GS",    new MaterialProps(11.0, 8.5, 6.0, 8.5, 11000.0, 1.0) },
            { "G1",    new MaterialProps(7.5, 7.5, 5.0, 7.5, 9000.0, 1.0) },
            { "G2",    new MaterialProps(5.4, 6.5, 4.0, 6.5, 8000.0, 1.0) },
            { "C24",   new MaterialProps(9.3, 8.0, 4.7, 8.0, 11000.0, 1.0) },
            { "C16",   new MaterialProps(5.2, 7.5, 3.5, 7.5, 8000.0, 1.0) }
        };

        public EW_Check_Compression()
            : base("EW_Check_Compression", "EW_Fc",
                  "Verifica compresión paralela a la fibra según NCh1198:2024 con pandeo (Kp).",
                  "RhinoSAP", "Checks")
        {
        }

        public override Guid ComponentGuid => new Guid("C95E341E-6241-4F12-A8B9-83B6E2C087F0");
        protected override System.Drawing.Bitmap Icon => null;

        protected override void RegisterInputParams(GH_InputParamManager pManager)
        {
            pManager.AddGenericParameter("Forces", "F", "Árbol de fuerzas axiales P (kN) por combo/elemento.", GH_ParamAccess.tree);
            pManager.AddTextParameter("Sections", "Sec", "Sección por elemento (p.ej. MGP10_33x73).", GH_ParamAccess.list);
            pManager.AddNumberParameter("Lengths", "L", "Longitud real del elemento (mm).", GH_ParamAccess.list);
            pManager.AddNumberParameter("Kp", "Kp", "Factor de longitud efectiva (1 o 2.5).", GH_ParamAccess.list, 1.0);
            pManager.AddNumberParameter("Kh", "Kh", "Factor humedad.", GH_ParamAccess.item, 0.85);
            pManager.AddNumberParameter("Kd", "Kd", "Factor duración de carga.", GH_ParamAccess.item, 1.0);
            pManager.AddNumberParameter("Khe", "Khe", "Factor de altura para Ef.", GH_ParamAccess.item, 1.0);
        }

        protected override void RegisterOutputParams(GH_OutputParamManager pManager)
        {
            pManager.AddNumberParameter("fc", "fc", "Tensión de trabajo por combo (MPa).", GH_ParamAccess.tree);
            pManager.AddNumberParameter("Fcp_dis", "Fcp,dis", "Tensión de diseño sin esbeltez (MPa) por elemento.", GH_ParamAccess.list);
            pManager.AddNumberParameter("Fcp_lam_dis", "Fcp,lam", "Tensión de diseño con esbeltez (MPa) por elemento.", GH_ParamAccess.list);
            pManager.AddNumberParameter("Util", "Util", "Utilización fc / Fcp_lam_dis por combo.", GH_ParamAccess.tree);
            pManager.AddBooleanParameter("OK", "OK", "Cumple (true) por combo.", GH_ParamAccess.tree);
            pManager.AddTextParameter("CriticalCombo", "Crit", "Combinación más desfavorable por elemento.", GH_ParamAccess.list);
            pManager.AddTextParameter("Verif", "Verif", "Detalle de cálculo (memoria) por elemento.", GH_ParamAccess.list);
            pManager.AddTextParameter("ControlForce", "Ctrl", "Fuerza usada en el control (P y combo) por elemento.", GH_ParamAccess.list);
            pManager.AddTextParameter("Messages", "Msg", "Mensajes y advertencias.", GH_ParamAccess.list);
        }

        protected override void SolveInstance(IGH_DataAccess DA)
        {
            if (!DA.GetDataTree(0, out GH_Structure<IGH_Goo> forcesTree) || forcesTree.Branches.Count == 0)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "Forces vacío o inválido.");
                return;
            }

            var sections = new List<string>();
            DA.GetDataList(1, sections);
            if (sections.Count == 0)
            {
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "Sections está vacío.");
                return;
            }

            var lengths = new List<double>();
            DA.GetDataList(2, lengths);

            var kpList = new List<double>();
            DA.GetDataList(3, kpList);

            double kh = 0.85;
            DA.GetData(4, ref kh);
            double kd = 1.0;
            DA.GetData(5, ref kd);
            double khe = 1.0;
            DA.GetData(6, ref khe);

            var fcTree = new GH_Structure<GH_Number>();
            var utilTree = new GH_Structure<GH_Number>();
            var okTree = new GH_Structure<GH_Boolean>();
            var fcpDisList = new List<double>();
            var fcpLamDisList = new List<double>();
            var critical = new List<string>();
            var verifList = new List<string>();
            var controlList = new List<string>();
            var messages = new List<string>();

            int elementCount = Math.Min(forcesTree.Branches.Count, Math.Min(sections.Count, lengths.Count == 0 ? int.MaxValue : lengths.Count));
            elementCount = Math.Min(elementCount, kpList.Count == 0 ? int.MaxValue : kpList.Count);

            for (int i = 0; i < elementCount; i++)
            {
                var branchPath = forcesTree.Paths[i];
                var branch = forcesTree.Branches[i];
                string sectionName = sections[i];
                double length = lengths.Count > i ? lengths[i] : 0.0;
                double kp = kpList.Count > i ? kpList[i] : 1.0;

                if (!TryParseSection(sectionName, out var material, out double b, out double h, messages))
                {
                    fcpDisList.Add(0);
                    fcpLamDisList.Add(0);
                    critical.Add($"{sectionName} -> Sección inválida");
                    continue;
                }

                if (!MaterialTable.TryGetValue(material, out var matProps))
                {
                    messages.Add($"[ERROR] Material '{material}' no soportado.");
                    fcpDisList.Add(0);
                    fcpLamDisList.Add(0);
                    critical.Add($"{sectionName} -> Material no soportado");
                    continue;
                }

                if (kp <= 0)
                {
                    messages.Add($"[WARN] Kp inválido para elemento {i} (valor {kp}); se usa 1.0.");
                    kp = 1.0;
                }

                double area = b * h; // mm2
                if (area <= 0)
                {
                    messages.Add($"[ERROR] Área inválida para '{sectionName}'.");
                    fcpDisList.Add(0);
                    fcpLamDisList.Add(0);
                    critical.Add($"{sectionName} -> Geometría inválida");
                    continue;
                }

                double lp = kp * length;
                double ix = h / Math.Sqrt(12.0);
                double iy = b / Math.Sqrt(12.0);
                double iMin = Math.Min(ix, iy);
                double lambda = iMin > 0 ? lp / iMin : double.PositiveInfinity;

                if (lambda > 200) messages.Add($"[WARN] Elemento {i} λ={Math.Round(lambda, 3)} supera 200.");
                else if (lambda > 170) messages.Add($"[WARN] Elemento {i} λ={Math.Round(lambda, 3)} supera 170.");

                double fcpDis = matProps.FcpPar * kh * kd;
                double fcpLamDis = fcpDis;
                double A = 0.0;
                double B = 0.0;
                double kLam = 1.0;

                if (lambda >= 10.0 && fcpDis > 0)
                {
                    double efDis = matProps.Ef * kh * khe;
                    double fCE = (3.6 * efDis) / (lambda * lambda);
                    A = ((fCE / fcpDis) * (1 + lambda / 200.0) + 1.0) / (2.0 * matProps.C);
                    B = fCE / (matProps.C * fcpDis);
                    double disc = Math.Max(0.0, A * A - B);
                    kLam = A - Math.Sqrt(disc);
                    fcpLamDis = fcpDis * kLam;
                }

                fcpDisList.Add(Math.Round(fcpDis, 2));
                fcpLamDisList.Add(Math.Round(fcpLamDis, 2));

                double worstUtil = double.MinValue;
                string worstCombo = "N/A";
                double worstFcp = 0.0;
                double worstP = 0.0;

                for (int j = 0; j < branch.Count; j++)
                {
                    var info = ParseForce(branch[j], messages);
                    if (info == null) continue;

                    // Compresión según convención: P < 0. Tracción o cero se ignoran.
                    if (info.P >= 0)
                    {
                        // Tracción o cero: no controla.
                        fcTree.Append(new GH_Number(0), branchPath);
                        utilTree.Append(new GH_Number(0), branchPath);
                        okTree.Append(new GH_Boolean(true), branchPath);
                        continue;
                    }

                    double fcp = (Math.Abs(info.P) * 1000.0) / area; // MPa
                    double util = (fcpLamDis > 0) ? fcp / fcpLamDis : 0.0;
                    bool ok = util <= 1.0 + 1e-9;

                    fcTree.Append(new GH_Number(Math.Round(fcp, 2)), branchPath);
                    utilTree.Append(new GH_Number(Math.Round(util, 2)), branchPath);
                    okTree.Append(new GH_Boolean(ok), branchPath);

                    if (util > worstUtil)
                    {
                        worstUtil = util;
                        worstCombo = info.Combo ?? $"idx{j}";
                        worstFcp = fcp;
                        worstP = info.P;
                    }
                }

                if (worstUtil < 0)
                {
                    worstUtil = 0;
                    worstCombo = "Sin compresión (P>=0)";
                    worstFcp = 0.0;
                    worstP = 0.0;
                }

                critical.Add($"{sectionName} -> {worstCombo} (util={Math.Round(worstUtil, 2)})");
                verifList.Add(
                    "Sección: " + sectionName +
                    " | Mat: " + material +
                    " | b=" + b + " mm, h=" + h + " mm, A=" + Math.Round(area, 4) + " mm2" +
                    " | Kp=" + Math.Round(kp, 4) + ", L=" + Math.Round(length, 4) + " mm, lp=Kp*L=" + Math.Round(lp, 4) + " mm" +
                    " | i=min(h/√12,b/√12)=" + Math.Round(iMin, 4) + " mm, λ=lp/i=" + Math.Round(lambda, 4) +
                    " | Fcp_dis=FcpPar*Kh*Kd=" + Math.Round(matProps.FcpPar, 4) + "*" + kh + "*" + kd + "=" + Math.Round(fcpDis, 2) + " MPa" +
                    (lambda >= 10.0 && fcpDis > 0
                        ? " | Ef_dis=Ef*Kh*Khe=" + Math.Round(matProps.Ef, 4) + "*" + kh + "*" + khe + "=" + Math.Round(matProps.Ef * kh * khe, 2) +
                          " | F_CE=3.6*Ef_dis/λ^2=" + Math.Round((3.6 * matProps.Ef * kh * khe) / (lambda * lambda), 2) +
                          " | A=((F_CE/Fcp_dis)*(1+λ/200)+1)/(2*C)=" + Math.Round(A, 2) +
                          " | B=F_CE/(C*Fcp_dis)=" + Math.Round(B, 2) +
                          " | K_λ=A-√(A²-B)=" + Math.Round(kLam, 2) +
                          " | Fcp_lam_dis=Fcp_dis*K_λ=" + Math.Round(fcpLamDis, 2) + " MPa"
                        : " | λ<10 => Fcp_lam_dis=Fcp_dis=" + Math.Round(fcpLamDis, 2) + " MPa") +
                    " | Combo crítico: " + worstCombo +
                    " | f_cp=|P|*1000/A=" + Math.Round(Math.Abs(worstFcp), 2) + " MPa" +
                    " | util=f_cp/Fcp_lam_dis=" + Math.Round(worstFcp, 2) + "/" + Math.Round(fcpLamDis, 2) + "=" + Math.Round(worstUtil, 2) +
                    " | OK=" + (worstUtil <= 1.0 + 1e-9 ? "✔" : "✖"));
                controlList.Add($"{sectionName} | Combo: {worstCombo} | P={Math.Round(worstP, 2)} kN");
            }

            DA.SetDataTree(0, fcTree);
            DA.SetDataList(1, fcpDisList);
            DA.SetDataList(2, fcpLamDisList);
            DA.SetDataTree(3, utilTree);
            DA.SetDataTree(4, okTree);
            DA.SetDataList(5, critical);
            DA.SetDataList(6, verifList);
            DA.SetDataList(7, controlList);
            DA.SetDataList(8, messages);
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
                return b > 0 && h > 0;
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

        private class MaterialProps
        {
            public MaterialProps(double ff, double fcpPerp, double ftp, double fcpPar, double ef, double c)
            {
                Ff = ff;
                FcpPerp = fcpPerp;
                Ftp = ftp;
                FcpPar = fcpPar;
                Ef = ef;
                C = c;
            }

            public double Ff { get; }
            public double FcpPerp { get; }
            public double Ftp { get; }
            public double FcpPar { get; }
            public double Ef { get; }
            public double C { get; }
        }

        private class ForceInfo
        {
            public string Combo { get; set; }
            public double P { get; set; }
        }
    }
}

