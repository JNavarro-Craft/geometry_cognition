using System;
using System.Collections.Generic;
using SAP2000v1;
using RhinoSAP.Core;

namespace RhinoSAP.SAP
{
    public class SapConfigurator
    {
        private readonly cSapModel _sapModel;
        private readonly SapLogger _logger;
        private readonly List<string> _executionLogs; // Logs locales garantizados
        private string _materialName = "MGP10";

        public List<string> ExecutionLogs => _executionLogs;

        public SapConfigurator(cSapModel sapModel, SapLogger logger)
        {
            _sapModel = sapModel;
            _logger = logger;
            _executionLogs = new List<string>();
        }

        private void Log(string msg, bool isError = false)
        {
            string prefix = isError ? "[ERROR] " : "[INFO] ";
            string finalMsg = prefix + msg;
            
            // Guardar en lista local (para asegurar output en GH)
            _executionLogs.Add(finalMsg);
            
            // Guardar en logger global (si funciona)
            if (isError) _logger.Error(msg);
            else _logger.Info(msg);
        }

        public void RunAllConfigurations()
        {
            Log("=== Iniciando Pre-configuración Automática (v2) ===");
            
            try
            {
                SetupUnits();
                SetupAnalysisDofs();
                SetupMaterials();
                SetupSections();
                SetupLoadPatterns();
                SetupLoadCombinations();
            }
            catch (Exception ex)
            {
                Log($"EXCEPCIÓN NO CONTROLADA EN CONFIGURACIÓN: {ex.Message}", true);
            }
            
            Log("=== Pre-configuración Completada ===");
        }

        private void SetupUnits()
        {
            try
            {
                _sapModel.SetPresentUnits(eUnits.kgf_m_C);
                Log("Unidades establecidas a kgf_m_C");
            }
            catch (Exception ex) { Log($"Error setting units: {ex.Message}", true); }
        }

        private void SetupAnalysisDofs()
        {
            try
            {
                int[] xzDofs = { 1, 3, 5 };
                var activeDofs = new bool[6];
                foreach (int dof in xzDofs)
                {
                    if (dof >= 1 && dof <= 6)
                    {
                        activeDofs[dof - 1] = true;
                    }
                }

                int ret = _sapModel.Analyze.SetActiveDOF(ref activeDofs);
                if (ret != 0)
                {
                    Log($"Could not set DOFs to XZ plane. SAP returned code {ret}.", true);
                }
                else
                {
                    Log("Analysis DOFs set to XZ plane (U1, U3, R2).");
                }
            }
            catch (Exception ex)
            {
                Log($"Error setting analysis DOFs: {ex.Message}", true);
            }
        }

        private void SetupMaterials()
        {
            Log("Configurando materiales...");
            _sapModel.SetPresentUnits(eUnits.kgf_m_C);

            string desiredName = "MGP10";
            try
            {
                // Intentar eliminar material previo con el mismo nombre para evitar conflictos de renombrado.
                _sapModel.PropMaterial.Delete(desiredName);
            }
            catch { /* Ignorar si no existe */ }
            string actualName = desiredName;
            int ret = -1;

            // ESTRATEGIA 1
            ret = TryAddMaterial(ref actualName, eMatType.NoDesign, "", "", "", "Intento 1");

            // ESTRATEGIA 2
            if (ret != 0)
            {
                actualName = desiredName;
                ret = TryAddMaterial(ref actualName, eMatType.NoDesign, "User", "None", "Default", "Intento 2");
            }

            // ESTRATEGIA 3
            if (ret != 0)
            {
                actualName = desiredName;
                try
                {
                    Log($"Intento 3: AddQuick {actualName}...");
                    ret = _sapModel.PropMaterial.AddQuick(ref actualName, eMatType.NoDesign, 0, 0, 0, 0, 0, 0);
                }
                catch (Exception ex)
                {
                    Log($"Intento 3 falló con excepción: {ex.Message}", true);
                    ret = -1;
                }
            }

            if (ret != 0)
            {
                Log($"FATAL: No se pudo crear el material '{desiredName}' con ningún método. Código final: {ret}", true);
                return;
            }

            // Intentar renombrar al nombre deseado si SAP lo cambió.
            if (!string.Equals(actualName, desiredName, StringComparison.OrdinalIgnoreCase))
            {
                Log($"SAP creó el material como '{actualName}'. Intentando renombrar a '{desiredName}'...");
                int renameRet = _sapModel.PropMaterial.ChangeName(actualName, desiredName);
                if (renameRet == 0)
                {
                    actualName = desiredName;
                    Log("Renombrado exitoso.");
                }
                else
                {
                    Log($"No se pudo renombrar '{actualName}' a '{desiredName}' (Error {renameRet}). Se usará el nombre generado.", true);
                }
            }

            _materialName = actualName;
            Log($"Material '{_materialName}' disponible. Configurando propiedades...");

            // Configurar propiedades mecánicas
            int retWM = _sapModel.PropMaterial.SetWeightAndMass(_materialName, 1, 480);
            if (retWM != 0) Log($"Error SetWeightAndMass: {retWM}", true);

            // E=1.02E8, U=0.3, A=1.17E-5, G=39230769
            int retMP = _sapModel.PropMaterial.SetMPIsotropic(_materialName, 1.0e9, 0.3, 1.17e-5, 39230769);
            if (retMP != 0) Log($"Error SetMPIsotropic: {retMP}", true);

            if (retWM == 0 && retMP == 0)
                Log($"Material '{_materialName}' configurado exitosamente.");
        }

        private void SetupSections()
        {
            Log("Configurando secciones...");
            _sapModel.SetPresentUnits(eUnits.kgf_m_C);

            string matName = _materialName ?? "MGP10";
            
            // Verificar existencia real
            eMatType tempType = eMatType.NoDesign;
            int tempColor = 0;
            string tempNotes = "";
            string tempGuid = "";
            int matExists = _sapModel.PropMaterial.GetMaterial(matName, ref tempType, ref tempColor, ref tempNotes, ref tempGuid);

            if (matExists != 0)
            {
                Log($"Abortando secciones: Material '{matName}' no se encuentra en el modelo (GetMaterial={matExists}).", true);
                return;
            }

            var sections = new[]
            {
                new { Name = "MGP10_33x73",  Depth = 0.073, Width = 0.033 },
                new { Name = "MGP10_33x95",  Depth = 0.095, Width = 0.033 },
                new { Name = "MGP10_33x145", Depth = 0.145, Width = 0.033 },
                new { Name = "MGP10_33x185", Depth = 0.185, Width = 0.033 },
                new { Name = "MGP10_41x145", Depth = 0.145, Width = 0.041 },
                new { Name = "MGP10_41x185", Depth = 0.185, Width = 0.041 }
            };

            foreach (var sec in sections)
            {
                int ret = _sapModel.PropFrame.SetRectangle(sec.Name, matName, sec.Depth, sec.Width, -1, "", "");
                if (ret == 0)
                    Log($"Sección '{sec.Name}' OK.");
                else
                    Log($"Error creando sección '{sec.Name}': {ret}", true);
            }
        }

        private void SetupLoadPatterns()
        {
            Log("Configurando Load Patterns...");
            var patterns = new[]
            {
                new { Name = "PESO PROPIO",   Type = eLoadPatternType.Dead, SelfWeight = 1.0 },
                new { Name = "MUERTA", Type = eLoadPatternType.Dead, SelfWeight = 0.0 },
                new { Name = "VIVA",   Type = eLoadPatternType.Live, SelfWeight = 0.0 },
                new { Name = "VIENTO", Type = eLoadPatternType.Wind, SelfWeight = 0.0 },
                new { Name = "NIEVE",  Type = eLoadPatternType.Snow, SelfWeight = 0.0 }
            };

            foreach (var pat in patterns)
            {
                _sapModel.LoadPatterns.Add(pat.Name, pat.Type, pat.SelfWeight, true);
            }
        }

        private void SetupLoadCombinations()
        {
            Log("Configurando Load Combinations...");
            CreateCombo("D", new[] { ("PESO PROPIO", 1.0), ("MUERTA", 1.0) });
            CreateCombo("D+L", new[] { ("D", 1.0), ("VIVA", 1.0) });
            CreateCombo("D+W", new[] { ("D", 1.0), ("VIENTO", 1.0) });
            
            CreateCombo("D+0,75L+0,75W+0,75S", new[] { 
                ("D", 1.0), ("VIVA", 0.75), ("VIENTO", 0.75), ("NIEVE", 0.75) 
            });

            CreateCombo("0,6D+W", new[] { ("D", 0.6), ("VIENTO", 1.0) });
            CreateCombo("D+S", new[] { ("D", 1.0), ("NIEVE", 1.0) });
            
            CreateCombo("D+0,75L+0,75S", new[] { 
                ("D", 1.0), ("VIVA", 0.75), ("NIEVE", 0.75) 
            });

            var envelopeCases = new[] {
                ("D", 1.0), ("D+L", 1.0), ("D+W", 1.0),
                ("D+0,75L+0,75W+0,75S", 1.0), ("0,6D+W", 1.0),
                ("D+S", 1.0), ("D+0,75L+0,75S", 1.0)
            };
            CreateCombo("ENVOLVENTE", envelopeCases, isEnvelope: true);
        }

        private void CreateCombo(string comboName, (string CaseName, double Scale)[] items, bool isEnvelope = false)
        {
            int type = isEnvelope ? 1 : 0;
            _sapModel.RespCombo.Delete(comboName);
            _sapModel.RespCombo.Add(comboName, type);

            foreach (var item in items)
            {
                eCNameType caseType = IsCombo(item.CaseName) ? eCNameType.LoadCombo : eCNameType.LoadCase;
                _sapModel.RespCombo.SetCaseList(comboName, ref caseType, item.CaseName, item.Scale);
            }
        }

        private bool IsCombo(string name)
        {
            return name == "D" || name.Contains("+") || name == "ENVOLVENTE";
        }

        private int TryAddMaterial(ref string matName, eMatType type, string region, string standard, string grade, string label)
        {
            try
            {
                Log($"{label}: AddMaterial {matName} (Region={region}, Std={standard}, Grade={grade})...");
                return _sapModel.PropMaterial.AddMaterial(ref matName, type, region, standard, grade);
            }
            catch (Exception ex)
            {
                Log($"{label} lanzó excepción: {ex.Message}", true);
                return -1;
            }
        }
    }
}
