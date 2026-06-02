using System;
using System.Collections.Generic;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Types;
using RhinoSAP.Core;
using RhinoSAP.SAP;
using SAP2000v1;

namespace RhinoSAP.Grasshopper
{
    /// <summary>
    /// Inicializa SAP2000 y expone el SapModel a GH/otros componentes.
    /// </summary>
    public class GH_InitializeSAP : GH_Component
    {
        private SapConnector _connector;

        public GH_InitializeSAP()
            : base("Initialize SAP", "InitSAP",
                  "Inicia o adjunta SAP2000 y aplica preconfiguraciones.",
                  "RhinoSAP", "Connection")
        {
        }

        public override Guid ComponentGuid => new Guid("A1B2C3D4-E5F6-4789-A012-3456789ABCDE");
        protected override System.Drawing.Bitmap Icon => null;

        protected override void RegisterInputParams(GH_InputParamManager pManager)
        {
            pManager.AddBooleanParameter("RunSAP", "Run", "Pulso para iniciar/adjuntar SAP", GH_ParamAccess.item, false);
            pManager.AddBooleanParameter("Attach", "Attach", "Adjuntarse a instancia existente", GH_ParamAccess.item, false);
            pManager.AddTextParameter("Program Path", "Path", "Ruta opcional a SAP2000.exe", GH_ParamAccess.item);
            pManager.AddBooleanParameter("Show UI", "UI", "Mostrar interfaz de SAP", GH_ParamAccess.item, true);
            pManager[2].Optional = true;
        }

        protected override void RegisterOutputParams(GH_OutputParamManager pManager)
        {
            pManager.AddGenericParameter("SapModel", "Model", "Objeto cSapModel activo", GH_ParamAccess.item);
            pManager.AddTextParameter("Messages", "Msg", "Mensajes y logs", GH_ParamAccess.list);
            pManager.AddBooleanParameter("Success", "OK", "True si SAP está listo", GH_ParamAccess.item);
        }

        protected override void SolveInstance(IGH_DataAccess DA)
        {
            bool runSap = false;
            bool attach = false;
            string programPath = string.Empty;
            bool showUi = true;

            DA.GetData(0, ref runSap);
            DA.GetData(1, ref attach);
            DA.GetData(2, ref programPath);
            DA.GetData(3, ref showUi);

            if (_connector != null && !_connector.CheckProcessAlive())
            {
                _connector.ResetConnection();
                _connector = null;
            }

            _connector ??= new SapConnector();

            var messages = new List<string>();
            var configLogs = new List<string>();

            bool connectorRunning = _connector.IsRunning;
            bool shouldInitialize = runSap && !connectorRunning;

            if (shouldInitialize)
            {
                var options = new SapInitializationOptions
                {
                    AttachToInstance = attach,
                    SpecifyPath = !string.IsNullOrWhiteSpace(programPath),
                    ProgramPath = programPath ?? string.Empty,
                    ShowUI = showUi
                };

                int result = attach
                    ? _connector.AttachToRunningInstance()
                    : _connector.StartNewInstance(options);

                if (result != ErrorCodes.Success && result != ErrorCodes.AlreadyInitialized)
                {
                    messages.AddRange(_connector.Logger.Flush());
                    DA.SetData(0, null);
                    DA.SetDataList(1, messages);
                    DA.SetData(2, false);
                    AddRuntimeMessage(GH_RuntimeMessageLevel.Error, $"SAP initialization failed (code {result}).");
                    return;
                }

                connectorRunning = _connector.IsRunning;
            }
            else if (!runSap && !connectorRunning)
            {
                const string info = "SAP no ha sido iniciado aún. Pulse RunSAP una vez.";
                messages.Add(info);
                DA.SetData(0, null);
                DA.SetDataList(1, messages);
                DA.SetData(2, false);
                AddRuntimeMessage(GH_RuntimeMessageLevel.Remark, info);
                return;
            }
            else if (connectorRunning)
            {
                messages.Add("SAP ya estaba inicializado. Reutilizando instancia activa.");
            }

            object sapModelObj = connectorRunning ? _connector.GetSapModel() : null;
            bool success = sapModelObj is cSapModel;

            if (shouldInitialize && success)
            {
                try
                {
                    var model = (cSapModel)sapModelObj;
                    _connector.Logger.Info("Inicializando nuevo modelo en blanco...");
                    model.InitializeNewModel(eUnits.kgf_m_C);
                    model.File.NewBlank();
                    _connector.Logger.Info("Nuevo modelo en blanco listo.");

                    var configurator = new SapConfigurator(model, _connector.Logger);
                    configurator.RunAllConfigurations();
                    configLogs.AddRange(configurator.ExecutionLogs);
                }
                catch (Exception ex)
                {
                    string errMsg = $"Error crítico durante la pre-configuración: {ex.Message}";
                    _connector.Logger.Error(errMsg, ex);
                    configLogs.Add("[CRITICAL] " + errMsg);
                    success = false;
                }
            }

            messages.AddRange(_connector.Logger.Flush());
            if (configLogs.Count > 0)
            {
                messages.Add("--- CONFIG LOGS ---");
                messages.AddRange(configLogs);
            }

            DA.SetData(0, success ? new GH_ObjectWrapper(sapModelObj) : null);
            DA.SetDataList(1, messages);
            DA.SetData(2, success);

            if (success)
                AddRuntimeMessage(GH_RuntimeMessageLevel.Remark, "SAP2000 ready.");
            else
                AddRuntimeMessage(GH_RuntimeMessageLevel.Error, "SAP2000 initialization or configuration failed.");
        }
    }
}










