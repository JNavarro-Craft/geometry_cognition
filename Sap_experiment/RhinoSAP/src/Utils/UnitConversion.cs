using Rhino;
using Rhino.Geometry;

namespace RhinoSAP.Utils
{
    /// <summary>
    /// Utilities to convert Rhino geometry/lengths into SAP2000 units (meters).
    /// </summary>
    public static class UnitConversion
    {
        private static double? _cachedScale;
        private static uint _cachedDocSerial;

        /// <summary>
        /// Scale factor to convert from the active Rhino document units to SAP units (meters).
        /// </summary>
        public static double RhinoToSapScale
        {
            get
            {
                var doc = RhinoDoc.ActiveDoc;
                if (doc == null)
                {
                    return _cachedScale ??= 0.001; // Default mm -> m
                }

                if (_cachedScale.HasValue && _cachedDocSerial == doc.RuntimeSerialNumber)
                {
                    return _cachedScale.Value;
                }

                double scale = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters);
                if (scale <= 0)
                {
                    scale = 0.001;
                }

                _cachedDocSerial = doc.RuntimeSerialNumber;
                _cachedScale = scale;
                return scale;
            }
        }

        public static Point3d ToSap(Point3d point)
        {
            double factor = RhinoToSapScale;
            if (factor == 1.0)
                return point;

            return new Point3d(point.X * factor, point.Y * factor, point.Z * factor);
        }

        public static double ToSapLength(double length)
        {
            return length * RhinoToSapScale;
        }
    }
}










