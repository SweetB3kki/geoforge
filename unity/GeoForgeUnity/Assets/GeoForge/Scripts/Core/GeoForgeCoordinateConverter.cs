using System;
using UnityEngine;

namespace GeoForge
{
    public static class GeoForgeCoordinateConverter
    {
        public static bool IsFinite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
        public static Vector3 GeoForgeToUnity(double x, double y, double z)
        {
            if (!IsFinite(x) || !IsFinite(y) || !IsFinite(z) ||
                Math.Abs(x) > float.MaxValue || Math.Abs(y) > float.MaxValue || Math.Abs(z) > float.MaxValue)
                throw new ArgumentException("Coordinates must be finite and representable as Unity floats.");
            return new Vector3((float)x, (float)z, (float)y);
        }
        public static Vector3 GeoForgeToUnity(double[] point)
        {
            if (point == null || point.Length != 3) throw new ArgumentException("Expected coordinate [x,y,z].");
            return GeoForgeToUnity(point[0], point[1], point[2]);
        }
    }
}
