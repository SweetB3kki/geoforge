using System;
using System.Collections.Generic;
using UnityEngine;

namespace GeoForge
{
    public static class GeoForgeRoadGenerator
    {
        public static GeoForgeRoadNetworkBuilder.Result BuildNetwork(IList<GeoForgeRoad> roads, GeoForgeRoadGeometrySettings settings)
            => new GeoForgeRoadNetworkBuilder(settings).Build(roads);

        /// <summary>Legacy standalone segment strips and bevel joins, without junction/bridge processing.</summary>
        public static GeoForgeMeshData Build(GeoForgeRoad road)
        {
            if (road == null || road.path == null || !GeoForgeCoordinateConverter.IsFinite(road.width) || road.width <= 0 || road.width > 10000)
                throw new ArgumentException("Road requires a path and positive finite width (max 10 km).");
            var points = new List<Vector3>();
            foreach (var point in road.path)
            {
                var p = GeoForgeCoordinateConverter.GeoForgeToUnity(point);
                p.y = 0.03f; // Flat blockout; source elevations intentionally unused for roads.
                if (points.Count == 0 || (points[points.Count-1]-p).sqrMagnitude > 1e-12f) points.Add(p);
            }
            if (points.Count < 2) throw new ArgumentException("Road has fewer than two distinct points.");
            var mesh = new GeoForgeMeshData();
            Vector3 previousOffset = Vector3.zero;
            float halfWidth = (float)(road.width / 2);
            for (int i = 0; i < points.Count-1; i++)
            {
                var delta = points[i+1]-points[i];
                float length = (float)Math.Sqrt(delta.x*delta.x + delta.z*delta.z);
                var offset = new Vector3(-delta.z / length, 0, delta.x / length) * halfWidth;
                int start = mesh.Vertices.Count;
                mesh.Vertices.AddRange(new[] {points[i]+offset, points[i]-offset, points[i+1]+offset, points[i+1]-offset});
                mesh.AddUpTriangle(start, start+2, start+1);
                mesh.AddUpTriangle(start+1, start+2, start+3);
                if (i > 0 && (offset-previousOffset).sqrMagnitude > 1e-12f)
                {
                    int join = mesh.Vertices.Count;
                    mesh.Vertices.AddRange(new[] {points[i], points[i]+previousOffset, points[i]+offset,
                        points[i]-previousOffset, points[i]-offset});
                    mesh.AddUpTriangle(join,join+1,join+2);
                    mesh.AddUpTriangle(join,join+3,join+4);
                }
                previousOffset = offset;
            }
            return mesh;
        }
    }
}
