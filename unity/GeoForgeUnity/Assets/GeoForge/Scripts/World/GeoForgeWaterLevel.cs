using System;

namespace GeoForge
{
    public static class GeoForgeWaterLevel
    {
        public static float Resolve(GeoForgeArea area, GeoForgeTerrainSampler sampler)
        {
            if (area.water_level_m.HasValue)
            {
                double value = area.water_level_m.Value;
                if (!GeoForgeCoordinateConverter.IsFinite(value) || Math.Abs(value) > 100000)
                    throw new ArgumentException("Water level must be finite and within 100 km.");
                return (float)value;
            }
            return sampler.PolygonHeight(area.polygon, true);
        }
    }
}
