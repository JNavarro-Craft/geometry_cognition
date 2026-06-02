using System;
using System.IO;
using System.Runtime.InteropServices;
using SAP2000v1;

namespace RhinoSAP.Core
{
    /// <summary>
    /// Implementación concreta de ISapConnector para gestionar la vida de SAP2000.
    /// </summary>
    public class SapConnector : ISapConnector, IDisposable
    {
        private cHelper _helper;
        private cOAPI _sapObject;
        private cSapModel _sapModel;
        private bool _isInitialized;

        public SapConnector()
        {
            Logger = new SapLogger();
        }

        public bool IsRunning => CheckProcessAlive();
        public SapLogger Logger { get; }

        public int StartNewInstance(SapInitializationOptions options)
        {
            if (options == null)
            {
                Logger.Error("SapInitializationOptions no puede ser null.");
                return ErrorCodes.InvalidOptions;
            }

            if (!options.Validate(out var validationError))
            {
                Logger.Error($"Opciones inválidas: {validationError}");
                return ErrorCodes.InvalidOptions;
            }

            if (_isInitialized)
            {
                Logger.Warn("SAP2000 ya está inicializado. Use ApplicationExit() antes de iniciar otra instancia.");
                return ErrorCodes.AlreadyInitialized;
            }

            try
            {
                CreateHelper();

                if (options.SpecifyPath)
                {
                    if (!File.Exists(options.ProgramPath))
                    {
                        Logger.Error($"Ruta de SAP no encontrada: {options.ProgramPath}");
                        return ErrorCodes.ProgramPathNotFound;
                    }

                    Logger.Info($"Iniciando SAP2000 desde ruta personalizada: {options.ProgramPath}");
                    _sapObject = _helper.CreateObject(options.ProgramPath);
                }
                else
                {
                    Logger.Info("Iniciando SAP2000 mediante CreateObjectProgID (última versión instalada).");
                    _sapObject = _helper.CreateObjectProgID("CSI.SAP2000.API.SapObject");
                }

                Logger.Info($"ApplicationStart (ShowUI={options.ShowUI})...");
                var ret = _sapObject.ApplicationStart(eUnits.kgf_m_C, options.ShowUI, string.Empty);
                if (ret != 0)
                {
                    Logger.Error($"ApplicationStart retornó {ret}");
                    Cleanup();
                    return ErrorCodes.ApplicationStartFailed;
                }

                _sapModel = _sapObject.SapModel;
                _isInitialized = true;
                Logger.Info("SAP2000 iniciado correctamente.");

                if (!string.IsNullOrWhiteSpace(options.ModelPath))
                {
                    OpenModel(options.ModelPath);
                }

                return ErrorCodes.Success;
            }
            catch (COMException ex)
            {
                Logger.Error("Error COM al iniciar SAP2000", ex);
                Cleanup();
                return ErrorCodes.ComInteropError;
            }
            catch (Exception ex)
            {
                Logger.Error("Error inesperado al iniciar SAP2000", ex);
                Cleanup();
                return ErrorCodes.SapObjectCreationFailed;
            }
        }

        public int AttachToRunningInstance()
        {
            if (_isInitialized)
            {
                Logger.Warn("SAP2000 ya está inicializado. Use ApplicationExit() antes de adjuntar otra instancia.");
                return ErrorCodes.AlreadyInitialized;
            }

            try
            {
                CreateHelper();
                _sapObject = _helper.GetObject("CSI.SAP2000.API.SapObject");
                _sapModel = _sapObject.SapModel;
                _isInitialized = true;
                Logger.Info("Se adjuntó correctamente a la instancia existente de SAP2000.");
                return ErrorCodes.Success;
            }
            catch (COMException ex)
            {
                Logger.Error("No se encontró instancia en ejecución o la conexión falló.", ex);
                Cleanup();
                return ErrorCodes.InstanceNotRunning;
            }
            catch (Exception ex)
            {
                Logger.Error("Error inesperado al adjuntar a SAP2000.", ex);
                Cleanup();
                return ErrorCodes.SapObjectAttachmentFailed;
            }
        }

        public object GetSapModel()
        {
            return CheckProcessAlive() ? _sapModel : null;
        }

        public bool CheckProcessAlive()
        {
            if (!_isInitialized || _sapObject == null || _sapModel == null)
                return false;

            try
            {
                _sapModel.GetModelIsLocked();
                return true;
            }
            catch (COMException)
            {
                Logger.Warn("La instancia de SAP2000 ya no responde. Reseteando conexión.");
                ResetConnection();
                return false;
            }
            catch
            {
                ResetConnection();
                return false;
            }
        }

        public void ResetConnection()
        {
            Cleanup();
        }

        public int ApplicationExit()
        {
            if (!_isInitialized)
            {
                Logger.Warn("SAP2000 no está inicializado. Nada que cerrar.");
                return ErrorCodes.NotInitialized;
            }

            try
            {
                if (_sapObject != null)
                {
                    Logger.Info("Solicitando ApplicationExit a SAP2000...");
                    _sapObject.ApplicationExit(false);
                }

                Cleanup();
                Logger.Info("Conexión a SAP2000 cerrada correctamente.");
                return ErrorCodes.Success;
            }
            catch (COMException ex)
            {
                Logger.Error("Error COM al cerrar SAP2000.", ex);
                Cleanup();
                return ErrorCodes.ComInteropError;
            }
            catch (Exception ex)
            {
                Logger.Error("Error inesperado al cerrar SAP2000.", ex);
                Cleanup();
                return ErrorCodes.ComInteropError;
            }
        }

        private void CreateHelper()
        {
            Logger.Info("Creando instancia de cHelper...");
            try
            {
                _helper = new Helper();
            }
            catch
            {
                var helperType = Type.GetTypeFromProgID("SAP2000v1.Helper", true);
                _helper = (cHelper)Activator.CreateInstance(helperType);
            }
        }

        private void OpenModel(string modelPath)
        {
            if (!File.Exists(modelPath))
            {
                Logger.Warn($"El modelo especificado no existe: {modelPath}");
                return;
            }

            var ret = _sapModel.File.OpenFile(modelPath);
            if (ret == 0)
            {
                Logger.Info($"Modelo '{modelPath}' abierto exitosamente.");
            }
            else
            {
                Logger.Warn($"No se pudo abrir el modelo '{modelPath}' (código {ret}).");
            }
        }

        private void Cleanup()
        {
            try
            {
                if (_sapModel != null && Marshal.IsComObject(_sapModel))
                {
                    Marshal.ReleaseComObject(_sapModel);
                }
                _sapModel = null;

                if (_sapObject != null && Marshal.IsComObject(_sapObject))
                {
                    Marshal.ReleaseComObject(_sapObject);
                }
                _sapObject = null;

                if (_helper != null && Marshal.IsComObject(_helper))
                {
                    Marshal.ReleaseComObject(_helper);
                }
                _helper = null;

                _isInitialized = false;
            }
            catch (Exception ex)
            {
                Logger.Error("Error durante limpieza de recursos.", ex);
            }
        }

        public void Dispose()
        {
            ApplicationExit();
        }
    }
}










