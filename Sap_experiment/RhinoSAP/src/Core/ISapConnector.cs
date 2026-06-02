namespace RhinoSAP.Core
{
    /// <summary>
    /// Interfaz para conectar y gestionar instancias de SAP2000 OAPI.
    /// </summary>
    public interface ISapConnector
    {
        /// <summary>
        /// Indica si la instancia de SAP2000 está viva y disponible.
        /// </summary>
        bool IsRunning { get; }

        /// <summary>
        /// Logger asociado.
        /// </summary>
        SapLogger Logger { get; }

        int StartNewInstance(SapInitializationOptions options);
        int AttachToRunningInstance();

        /// <summary>
        /// Obtiene el cSapModel asociado.
        /// </summary>
        object GetSapModel();

        /// <summary>
        /// Valida si el proceso sigue vivo.
        /// </summary>
        bool CheckProcessAlive();

        /// <summary>
        /// Limpia referencias COM para permitir reiniciar el conector.
        /// </summary>
        void ResetConnection();

        int ApplicationExit();
    }
}









