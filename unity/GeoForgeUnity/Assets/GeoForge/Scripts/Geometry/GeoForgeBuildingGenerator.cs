using System;
using UnityEngine;

namespace GeoForge
{
    public static class GeoForgeBuildingGenerator
    {
        /// <summary>Extrude absolute scene coordinates. Building.position is not an offset.</summary>
        public static GeoForgeMeshData Build(GeoForgeBuilding building)
        {
            if (building == null || !GeoForgeCoordinateConverter.IsFinite(building.height) || building.height <= 0 || building.height > 100000)
                throw new ArgumentException("Building height must be positive and finite (max 100 km).");
            var polygon = GeoForgeTriangulator.Prepare(building.footprint);
            float height = (float)building.height;
            var mesh = GeoForgeTriangulator.Triangulate(polygon, height);
            // Independent vertices for roof, bottom, and each wall produce hard edges.
            int roofCount = mesh.Vertices.Count;
            int roofIndices = mesh.Triangles.Count;
            mesh.RoofTriangleIndexCount = roofIndices;
            for (int i = 0; i < roofCount; i++) mesh.Vertices.Add(mesh.Vertices[i] - Vector3.up * height);
            for (int i = 0; i < roofIndices; i += 3)
            {
                mesh.Triangles.Add(mesh.Triangles[i] + roofCount);
                mesh.Triangles.Add(mesh.Triangles[i+2] + roofCount);
                mesh.Triangles.Add(mesh.Triangles[i+1] + roofCount);
            }
            foreach (var ring in polygon.Rings)
                for (int i = 0; i < ring.Count; i++)
                {
                    var a = ring[i]; var b = ring[(i+1)%ring.Count];
                    int start = mesh.Vertices.Count;
                    mesh.Vertices.Add(a); mesh.Vertices.Add(a + Vector3.up * height);
                    mesh.Vertices.Add(b + Vector3.up * height); mesh.Vertices.Add(b);
                    mesh.Triangles.AddRange(new[] {start,start+1,start+2,start,start+2,start+3});
                }
            return mesh;
        }
    }
}
