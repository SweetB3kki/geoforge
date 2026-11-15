using System;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeRoadMeshSeamsTests
    {
        [Test]
        public void FineEdgeVertexSplitsCoarseNeighbourAndClosesHeightGap()
        {
            var source=new GeoForgeMeshData();
            source.Vertices.AddRange(new[]{new Vector3(0,0,0),new Vector3(4,0,0),new Vector3(0,0,4),new Vector3(2,1,0),new Vector3(2,0,-4)});
            source.AddUpTriangle(0,1,2);source.AddUpTriangle(0,4,3);source.AddUpTriangle(3,4,1);
            var before=source.Vertices.ToArray();var result=GeoForgeRoadMeshSeams.Conform(source);
            Assert.That(result.Triangles.Count,Is.GreaterThan(source.Triangles.Count));
            double area=0;
            for(int i=0;i<result.Triangles.Count;i+=3)
            {
                var a=result.Vertices[result.Triangles[i]];var b=result.Vertices[result.Triangles[i+1]];var c=result.Vertices[result.Triangles[i+2]];
                area+=Math.Abs(Vector3.Cross(b-a,c-a).y)/2;
            }
            Assert.That(area,Is.EqualTo(16).Within(0.00001));
            CollectionAssert.AreEqual(before,source.Vertices);
            var mesh=result.ToMesh("conforming");var go=new GameObject("seam collider");
            try
            {
                var collider=go.AddComponent<MeshCollider>();collider.sharedMesh=mesh;Physics.SyncTransforms();
                foreach(float z in new[]{-.001f,0,.001f})
                {
                    Assert.That(collider.Raycast(new Ray(new Vector3(2,10,z),Vector3.down),out var hit,20),Is.True);
                    Assert.That(hit.point.y,Is.EqualTo(1).Within(0.002));
                }
            }
            finally{UnityEngine.Object.DestroyImmediate(go);UnityEngine.Object.DestroyImmediate(mesh);}
            Assert.Throws<ArgumentException>(()=>GeoForgeRoadMeshSeams.Conform(source,3));
        }
    }
}
