using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace GeoForge
{
    /// <summary>Managed geometry, separately testable before creating a native Mesh.</summary>
    public sealed class GeoForgeMeshData
    {
        public readonly List<Vector3> Vertices = new List<Vector3>();
        public readonly List<int> Triangles = new List<int>();
        public int RoofTriangleIndexCount;
        public Mesh ToMesh(string name)
        {
            if (Vertices.Count == 0 || Triangles.Count == 0) throw new ArgumentException("Empty mesh.");
            var mesh = new Mesh { name = name, indexFormat = Vertices.Count > 65535 ? IndexFormat.UInt32 : IndexFormat.UInt16 };
            mesh.SetVertices(Vertices);
            if(RoofTriangleIndexCount>0)
            {
                mesh.subMeshCount=2;
                mesh.SetTriangles(Triangles.GetRange(RoofTriangleIndexCount,Triangles.Count-RoofTriangleIndexCount),0);
                mesh.SetTriangles(Triangles.GetRange(0,RoofTriangleIndexCount),1);
            }
            else mesh.SetTriangles(Triangles, 0);
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }
        public void AddUpTriangle(int a, int b, int c)
        {
            var cross = Vector3.Cross(Vertices[b] - Vertices[a], Vertices[c] - Vertices[a]);
            if (cross.y < 0) { int swap = b; b = c; c = swap; }
            Triangles.Add(a); Triangles.Add(b); Triangles.Add(c);
        }
    }
}
