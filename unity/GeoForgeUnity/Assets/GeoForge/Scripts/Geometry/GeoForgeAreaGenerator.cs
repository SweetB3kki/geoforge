using System;
using System.Collections.Generic;
using System.Linq;

namespace GeoForge
{
    public static class GeoForgeAreaGenerator
    {
        public static GeoForgeMeshData RemoveWaterCover(GeoForgeMeshData land,IEnumerable<GeoForgeArea> waters)
        {
            var masks=waters.Select(Build).ToArray();
            return masks.Length==0?land:GeoForgeGroundCutout.SubtractPreservingPlanes(land,masks);
        }
        public static GeoForgeMeshData Build(GeoForgeArea area)
        {
            if (area == null || (area.area_type != "water" && area.area_type != "green"))
                throw new ArgumentException("Expected water or green area.");
            return GeoForgeTriangulator.Triangulate(GeoForgeTriangulator.Prepare(area.polygon),
                area.area_type == "water" ? 0.01f : 0.015f);
        }
    }
}
