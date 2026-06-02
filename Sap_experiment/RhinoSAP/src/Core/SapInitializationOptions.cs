namespace RhinoSAP.Core
{
    /// <summary>
    /// Opciones de inicialización para SAP2000 OAPI.
    /// </summary>
    public class SapInitializationOptions
    {
        /// <summary>
        /// Si es true, intenta adjuntarse a una instancia existente.
        /// </summary>
        public bool AttachToInstance { get; set; }

        /// <summary>
        /// Si es true, utiliza ProgramPath en lugar de CreateObjectProgID.
        /// </summary>
        public bool SpecifyPath { get; set; }

        /// <summary>
        /// Ruta completa al ejecutable de SAP2000.
        /// </summary>
        public string ProgramPath { get; set; } = string.Empty;

        /// <summary>
        /// Ruta de un modelo .sdb opcional a abrir.
        /// </summary>
        public string ModelPath { get; set; } = string.Empty;

        /// <summary>
        /// Controla si se muestra la UI al iniciar SAP.
        /// </summary>
        public bool ShowUI { get; set; } = true;

        public bool Validate(out string errorMessage)
        {
            errorMessage = string.Empty;

            if (SpecifyPath && string.IsNullOrWhiteSpace(ProgramPath))
            {
                errorMessage = "ProgramPath debe especificarse cuando SpecifyPath es true.";
                return false;
            }

            return true;
        }
    }
}









