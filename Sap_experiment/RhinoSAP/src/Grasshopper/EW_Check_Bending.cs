using System;
using System.Collections.Generic;
using System.Globalization;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Data;
using Grasshopper.Kernel.Types;

namespace RhinoSAP.Grasshopper
{
    /// <summary>
    /// Verifica flexión (M3) según NCh1198:2024, incluyendo flexo-tracción y flexo-compresión.
    /// </summary>
    public class EW_Check_Bending : GH_Component
    {
        private const double Kh = 0.85; // Humedad
        private const double Kd = 1.0;  // Duración
        private const double Kc = 1.0;  // Condición de servicio

        private static readonly Dictionary<string, MaterialProps> MaterialTable = new(StringComparer.OrdinalIgnoreCase)
        {
            // Valores extendidos con FcpPar, Ef y C (aproximados, ajustar según NCh1198).
            { "MGP10", new MaterialProps(8.4, 10.0, 4.0, 10.0, 10000.0, 1.0) },
            { "MGP12", new MaterialProps(13.5, 15.5, 6.0, 15.5, 12000.0, 1.0) },
            { "GS",    new MaterialProps(11.0, 8.5, 6.0, 8.5, 11000.0, 1.0) },
            { "G1",    new MaterialProps(7.5, 7.5, 5.0, 7.5, 9000.0, 1.0) },
            { "G2",    new MaterialProps(5.4, 6.5, 4.0, 6.5, 8000.0, 1.0) },
            { "C24",   new MaterialProps(9.3, 8.0, 4.7, 8.0, 11000.0, 1.0) },
            { "C16",   new MaterialProps(5.2, 7.5, 3.5, 7.5, 8000.0, 1.0) }
        };

        public EW_Check_Bending()
            : base("EW_Check_Bending", "EW_Flex",
                  "Verifies bending (M3) per NCh1198:2024 with flexo-tracción y flexo-compresión.",
                  "RhinoSAP", "Checks")
        {
        }

        public override Guid ComponentGuid => new Guid("F0E5C26F-4F6F-4D13-BD8E-0F3F93C20B77");
        protected override System.Drawing.Bitmap Icon => null;

        protected override void RegisterInputParams(GH_InputParamManager pManager)
        {
            pManager.AddGenericParameter("Forces", "F", "Resultados por elemento/combos (tree) con P y M3.", GH_ParamAccess.tree);
            pManager.AddTextParameter("Sections", "Sec", "Sección por elemento (p.ej. MGP10_33x73).", GH_ParamAccess.list);
            pManager.AddNumberParameter("Lengths", "Len", "Longitud de cada frame (mm), mismo orden que Sections.", GH_ParamAccess.list);
            pManager.AddNumberParameter("Lv_spacing", "Lv", "Separación entre arriostramientos intermedios (mm).", GH_ParamAccess.item, 600.0);
            pManager.AddNumberParameter("Khf", "Khf", "Factor de homogenización (flexión).", GH_ParamAccess.item, 0.85);
        }

        protected override void RegisterOutputParams(GH_OutputParamManager pManager)
        {
            pManager.AddNumberParameter("ff", "ff", "Tensión de flexión por combo (MPa).", GH_ParamAccess.tree);
            pManager.AddNumberParameter("Fb_ft", "Fb_ft", "Tensión de diseño flexo-tracción (MPa) por elemento.", GH_ParamAccess.list);
            pManager.AddNumberParameter("Fb_fc", "Fb_fc", "Tensión de diseño flexo-compresión (MPa) por elemento.", GH_ParamAccess.list);
            pManager.AddNumberParameter("util_ft", "util_ft", "Utilización flexo-tracción por combo.", GH_ParamAccess.tree);
            pManager.AddNumberParameter("util_fc", "util_fc", "Utilización flexo-compresión por combo.", GH_ParamAccess.tree);
            pManager.AddBooleanParameter("OK_ft", "OK_ft", "Cumple flexo-tracción por combo.", GH_ParamAccess.tree);
            pManager.AddBooleanParameter("OK_fc", "OK_fc", "Cumple flexo-compresión por combo.", GH_ParamAccess.tree);
            pManager.AddTextParameter("CriticalCombo", "Crit", "Combo/control más desfavorable por elemento.", GH_ParamAccess.list);
            pManager.AddTextParameter("ControlForce", "Ctrl", "Fuerza usada en el control (P y M3) por elemento.", GH_ParamAccess.list);
            pManager.AddTextParameter("Verif", "Verif", "Detalle de cálculo (memoria) por elemento.", GH_ParamAccess.list);
            pManager.AddTextParameter("Messages", "Msg", "Mensajes de verificación.", GH_ParamAccess.list);
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

            double lvSpacing = 600.0;
            DA.GetData(3, ref lvSpacing);
            lvSpacing = Math.Max(0.0, lvSpacing);

            double khf = 0.85;
            DA.GetData(4, ref khf);
            khf = Math.Max(0.0, khf);

            var ffTree = new GH_Structure<GH_Number>();
            var utilFtTree = new GH_Structure<GH_Number>();
            var utilFcTree = new GH_Structure<GH_Number>();
            var okFtTree = new GH_Structure<GH_Boolean>();
            var okFcTree = new GH_Structure<GH_Boolean>();
            var fbFtList = new List<double>();
            var fbFcList = new List<double>();
            var critical = new List<string>();
            var controlList = new List<string>();
            var verifList = new List<string>();
            var messages = new List<string>();

            int branchCount = forcesTree.Branches.Count;
            int elementCount = Math.Min(branchCount, Math.Min(sections.Count, lengths.Count == 0 ? int.MaxValue : lengths.Count));
            for (int i = 0; i < elementCount; i++)
            {
                var branchPath = forcesTree.Paths[i];
                var branch = forcesTree.Branches[i];
                var elementPath = branchPath;
                string sectionName = sections[i];
                double length = lengths.Count > i ? lengths[i] : 0.0;

                if (!TryParseSection(sectionName, out var material, out double b, out double h, messages))
                {
                    fbFtList.Add(0);
                    fbFcList.Add(0);
                    critical.Add($"{sectionName} -> Sección inválida");
                    continue;
                }

                if (!MaterialTable.TryGetValue(material, out var matProps))
                {
                    messages.Add($"[ERROR] Material '{material}' no soportado.");
                    fbFtList.Add(0);
                    fbFcList.Add(0);
                    critical.Add($"{sectionName} -> Material no soportado");
                    continue;
                }

                double area = b * h; // mm2
                double wn = (b * h * h) / 6.0; // mm3
                if (area <= 0 || wn <= 0)
                {
                    messages.Add($"[ERROR] Área o módulo de sección inválidos para '{sectionName}'.");
                    fbFtList.Add(0);
                    fbFcList.Add(0);
                    critical.Add($"{sectionName} -> Geometría inválida");
                    continue;
                }

                double lvEff = length <= 0 ? lvSpacing : Math.Min(length, lvSpacing <= 0 ? length : lvSpacing);
                double lambda = b <= 0 ? 0.0 : (lvEff * h) / (b * b);
                double hbRatio = b <= 0 ? 0.0 : h / b;
                double kLambdaV = hbRatio <= 2.0 ? 1.0 : 1.0 / (1.0 + (lambda * lambda / 15000.0));
                if (lambda > 50.0)
                {
                    messages.Add($"[WARN] λv={Math.Round(lambda, 2)} supera el recomendado (>50) en '{sectionName}'.");
                }

                double fbFt = matProps.Ff * Kh * Kd * Kc * khf;
                double fbFc = matProps.Ff * Kh * Kd * Kc * kLambdaV;
                fbFtList.Add(Math.Round(fbFt, 2));
                fbFcList.Add(Math.Round(fbFc, 2));

                double worstUtil = double.MinValue;
                string worstCombo = "N/A";
                string worstMode = "N/A";
                double worstP = 0.0;
                double worstM3 = 0.0;
                double worstFf = 0.0;
                double worstAxial = 0.0;
                double worstFtEff = 0.0;
                double worstFcEff = 0.0;
                double worstUtilFt = 0.0;
                double worstUtilFc = 0.0;

                for (int j = 0; j < branch.Count; j++)
                {
                    var info = ParseForce(branch[j], messages);
                    if (info == null) continue;

                    double ff = wn > 0 ? Math.Abs(info.M3) / wn : 0.0; // MPa
                    double axial = (info.P * 1000.0) / area; // MPa (P en kN)

                    double ftEff = ff + axial;
                    double fcEff = ff - axial;

                    double utilFt = fbFt > 0 ? ftEff / fbFt : 0.0;
                    double utilFc = fbFc > 0 ? fcEff / fbFc : 0.0;

                    bool okFt = utilFt <= 1.0 + 1e-9;
                    bool okFc = utilFc <= 1.0 + 1e-9;

                    ffTree.Append(new GH_Number(Math.Round(ff, 2)), elementPath);
                    utilFtTree.Append(new GH_Number(Math.Round(utilFt, 2)), elementPath);
                    utilFcTree.Append(new GH_Number(Math.Round(utilFc, 2)), elementPath);
                    okFtTree.Append(new GH_Boolean(okFt), elementPath);
                    okFcTree.Append(new GH_Boolean(okFc), elementPath);

                    if (utilFt > worstUtil)
                    {
                        worstUtil = utilFt;
                        worstCombo = info.Combo ?? $"idx{j}";
                        worstMode = "FT";
                        worstP = info.P;
                        worstM3 = info.M3;
                        worstFf = ff;
                        worstAxial = axial;
                        worstFtEff = ftEff;
                        worstFcEff = fcEff;
                        worstUtilFt = utilFt;
                        worstUtilFc = utilFc;
                    }

                    if (utilFc > worstUtil)
                    {
                        worstUtil = utilFc;
                        worstCombo = info.Combo ?? $"idx{j}";
                        worstMode = "FC";
                        worstP = info.P;
                        worstM3 = info.M3;
                        worstFf = ff;
                        worstAxial = axial;
                        worstFtEff = ftEff;
                        worstFcEff = fcEff;
                        worstUtilFt = utilFt;
                        worstUtilFc = utilFc;
                    }
                }

                if (worstUtil < 0)
                {
                    worstUtil = 0;
                    worstCombo = "Sin datos";
                    worstMode = "N/A";
                    worstP = 0.0;
                    worstM3 = 0.0;
                    worstFf = 0.0;
                    worstAxial = 0.0;
                    worstFtEff = 0.0;
                    worstFcEff = 0.0;
                    worstUtilFt = 0.0;
                    worstUtilFc = 0.0;
                }

                critical.Add($"{sectionName} -> {worstCombo} ({worstMode}, util={Math.Round(worstUtil, 2)})");
                messages.Add($"[DBG] elem {i} ({sectionName}) worst={worstMode}:{worstCombo} util={Math.Round(worstUtil, 2)}");
                controlList.Add($"{sectionName} | Mode: {worstMode} | Combo: {worstCombo} | P={Math.Round(worstP, 2)} kN | M3={Math.Round(worstM3, 2)} Nmm");
                verifList.Add(
                    "Sección: " + sectionName +
                    " | Mat: " + material +
                    " | b=" + b + " mm, h=" + h + " mm, A=" + Math.Round(area, 4) + " mm2, Wn=" + Math.Round(wn, 4) + " mm3" +
                    " | Long=" + Math.Round(length, 4) + " mm, Lv_eff=min(Long,Lv_spacing)=" + Math.Round(lvEff, 4) + " mm, λv=(Lv_eff*h)/(b^2)=" + Math.Round(lambda, 4) + ", Kλv=" + Math.Round(kLambdaV, 2) +
                    " | Fb_ft=Ff*Kh*Kd*Kc*Khf=" + Math.Round(matProps.Ff, 4) + "*" + Kh + "*" + Kd + "*" + Kc + "*" + Math.Round(khf, 4) + "=" + Math.Round(fbFt, 2) + " MPa" +
                    " | Fb_fc=Ff*Kh*Kd*Kc*Kλv=" + Math.Round(matProps.Ff, 4) + "*" + Kh + "*" + Kd + "*" + Kc + "*" + Math.Round(kLambdaV, 2) + "=" + Math.Round(fbFc, 2) + " MPa" +
                    " | Combo crítico: " + worstCombo + " (" + worstMode + ")" +
                    " | P=" + Math.Round(worstP, 2) + " kN, M3=" + Math.Round(worstM3, 2) + " Nmm" +
                    " | ff=|M3|/Wn=" + Math.Round(Math.Abs(worstM3), 2) + "/" + Math.Round(wn, 4) + "=" + Math.Round(worstFf, 2) + " MPa" +
                    " | axial=P*1000/A=" + Math.Round(worstP, 2) + "*1000/" + Math.Round(area, 4) + "=" + Math.Round(worstAxial, 2) + " MPa" +
                    " | ft_eff=ff+axial=" + Math.Round(worstFf, 2) + "+" + Math.Round(worstAxial, 2) + "=" + Math.Round(worstFtEff, 2) + " MPa" +
                    " | fc_eff=ff-axial=" + Math.Round(worstFf, 2) + "-" + Math.Round(worstAxial, 2) + "=" + Math.Round(worstFcEff, 2) + " MPa" +
                    " | util_ft=ft_eff/Fb_ft=" + Math.Round(worstFtEff, 2) + "/" + Math.Round(fbFt, 2) + "=" + Math.Round(worstUtilFt, 2) +
                    " | util_fc=fc_eff/Fb_fc=" + Math.Round(worstFcEff, 2) + "/" + Math.Round(fbFc, 2) + "=" + Math.Round(worstUtilFc, 2) +
                    " | OK = " + (worstMode == "FT" ? (worstUtilFt <= 1.0 + 1e-9 ? "✔" : "✖") : (worstUtilFc <= 1.0 + 1e-9 ? "✔" : "✖")));
            }

            DA.SetDataTree(0, ffTree);
            DA.SetDataList(1, fbFtList);
            DA.SetDataList(2, fbFcList);
            DA.SetDataTree(3, utilFtTree);
            DA.SetDataTree(4, utilFcTree);
            DA.SetDataTree(5, okFtTree);
            DA.SetDataTree(6, okFcTree);
            DA.SetDataList(7, critical);
            DA.SetDataList(8, controlList);
            DA.SetDataList(9, verifList);
            DA.SetDataList(10, messages);
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
                        P = fr.P,
                        M3 = fr.M3
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
                double m3Val = 0.0;

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

                int mIdx = text.IndexOf("M3=", StringComparison.OrdinalIgnoreCase);
                if (mIdx >= 0)
                {
                    int sep = text.IndexOf(',', mIdx);
                    string mStr = sep > mIdx ? text.Substring(mIdx + 3, sep - (mIdx + 3)) : text.Substring(mIdx + 3);
                    double.TryParse(mStr, NumberStyles.Any, CultureInfo.InvariantCulture, out m3Val);
                }

                return new ForceInfo { Combo = combo, P = pVal, M3 = m3Val };
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
            public double P { get; set; }  // kN
            public double M3 { get; set; } // N·mm (o kN·m si se detecta y convierte)
        }
    }
}

