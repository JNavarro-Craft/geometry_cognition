using System;
using System.IO;

namespace RhinoSAP.Utils
{
    /// <summary>
    /// Utilidades para localizar rutas de instalación de SAP2000.
    /// </summary>
    public static class PathResolver
    {
        private const string DefaultInstallPath32 = @"C:\Program Files (x86)\Computers and Structures\SAP2000";
        private const string DefaultInstallPath64 = @"C:\Program Files\Computers and Structures\SAP2000";
        private const string ExecutableName = "SAP2000.exe";

        public static string FindSapExecutable(string preferredVersion = null)
        {
            if (!string.IsNullOrWhiteSpace(preferredVersion))
            {
                var path = Path.Combine(DefaultInstallPath64, $"SAP2000 {preferredVersion}", ExecutableName);
                if (File.Exists(path)) return path;

                path = Path.Combine(DefaultInstallPath32, $"SAP2000 {preferredVersion}", ExecutableName);
                if (File.Exists(path)) return path;
            }

            var latest = FindLatest(DefaultInstallPath64);
            if (!string.IsNullOrEmpty(latest)) return latest;

            latest = FindLatest(DefaultInstallPath32);
            return latest;
        }

        public static bool IsValidExecutable(string path)
        {
            return !string.IsNullOrWhiteSpace(path) &&
                   File.Exists(path) &&
                   string.Equals(Path.GetFileName(path), ExecutableName, StringComparison.OrdinalIgnoreCase);
        }

        private static string FindLatest(string basePath)
        {
            if (!Directory.Exists(basePath))
                return null;

            string latestPath = null;
            int latestVersion = -1;

            foreach (var directory in Directory.GetDirectories(basePath))
            {
                var dirName = Path.GetFileName(directory);
                if (!dirName.StartsWith("SAP2000 ", StringComparison.OrdinalIgnoreCase))
                    continue;

                if (int.TryParse(dirName.Substring("SAP2000 ".Length), out int version))
                {
                    var candidate = Path.Combine(directory, ExecutableName);
                    if (File.Exists(candidate) && version > latestVersion)
                    {
                        latestVersion = version;
                        latestPath = candidate;
                    }
                }
            }

            return latestPath;
        }
    }
}









