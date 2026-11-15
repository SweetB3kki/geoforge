using System;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeRoadBanksTests
    {
        private static GeoForgeMeshData Rect(float x0,float z0,float x1,float z1,float height)
        {
            var m=new GeoForgeMeshData();m.Vertices.AddRange(new[]{new Vector3(x0,height,z0),new Vector3(x1,height,z0),new Vector3(x1,height,z1),new Vector3(x0,height,z1)});
            m.AddUpTriangle(0,1,2);m.AddUpTriangle(0,2,3);return m;
        }
        private static double Area(GeoForgeMeshData mesh)
        {
            double result=0;
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var a=mesh.Vertices[mesh.Triangles[i]];var b=mesh.Vertices[mesh.Triangles[i+1]];var c=mesh.Vertices[mesh.Triangles[i+2]];
                result+=Vector3.Cross(b-a,c-a).magnitude/2;
            }
            return result;
        }
        [Test]
        public void InteriorSurfaceFacesAreNotIndexedAndCannotAlterBoundaryCaps()
        {
            var mask=Rect(-10,-10,10,10,0);var road=Rect(-10,-10,10,10,6);
            var land=GeoForgeGroundCutout.Subtract(Rect(-20,-20,20,20,10),new[]{mask});
            var baseline=GeoForgeRoadBanks.Build(land,new[]{mask},new[]{road});
            var withInterior=GeoForgeRoadBanks.Build(land,new[]{mask},new[]{road,Rect(-1,-1,1,1,100)});
            Assert.That(withInterior.SurfaceTrianglesScanned,Is.EqualTo(4));
            Assert.That(withInterior.SurfaceTrianglesIndexed,Is.EqualTo(2));
            CollectionAssert.AreEqual(baseline.Mesh.Vertices,withInterior.Mesh.Vertices);
            CollectionAssert.AreEqual(baseline.Mesh.Triangles,withInterior.Mesh.Triangles);
            Assert.That(withInterior.MissingRoadSurfaceMeters,Is.EqualTo(baseline.MissingRoadSurfaceMeters));
        }
        [Test]
        public void ClosedCutHasBothSidedWallsWithExactLandAndRoadHeights()
        {
            var mask=Rect(-1,-1,1,1,0);var road=Rect(-1,-1,1,1,6);
            var land=GeoForgeGroundCutout.Subtract(Rect(-5,-5,5,5,10),new[]{mask});
            var original=land.Vertices.ToArray();
            var result=GeoForgeRoadBanks.Build(land,new[]{mask},new[]{road});
            Assert.That(result.MissingRoadSurfaceMeters,Is.LessThan(0.001));
            Assert.That(result.MaximumHeightDifferenceMeters,Is.EqualTo(4).Within(0.0001));
            Assert.That(Area(result.Mesh),Is.EqualTo(64).Within(0.01));
            foreach(var p in result.Mesh.Vertices)Assert.That(p.y==6||p.y==10,Is.True);
            CollectionAssert.AreEqual(original,land.Vertices);
            Assert.That(road.Vertices.All(p=>p.y==6),Is.True);
            var go=new GameObject("bank collider");var mesh=result.Mesh.ToMesh("banks");
            try
            {
                var collider=go.AddComponent<MeshCollider>();collider.sharedMesh=mesh;Physics.SyncTransforms();
                Assert.That(collider.Raycast(new Ray(new Vector3(0,8,0),Vector3.right),out var hit,3),Is.True);
                Assert.That(hit.point.x,Is.EqualTo(1).Within(0.001));
                Assert.That(collider.Raycast(new Ray(new Vector3(2,8,0),Vector3.left),out hit,3),Is.True);
                Assert.That(hit.point.x,Is.EqualTo(1).Within(0.001));
            }
            finally{UnityEngine.Object.DestroyImmediate(go);UnityEngine.Object.DestroyImmediate(mesh);}
        }
        [Test]
        public void OverlappingRoadsHaveNoInternalWalls()
        {
            var masks=new[]{Rect(-2,-1,1,1,0),Rect(-1,-1,2,1,0)};
            var roads=new[]{Rect(-2,-1,1,1,6),Rect(-1,-1,2,1,6)};
            var land=GeoForgeGroundCutout.Subtract(Rect(-5,-5,5,5,10),masks);
            var result=GeoForgeRoadBanks.Build(land,masks,roads);
            Assert.That(Area(result.Mesh),Is.EqualTo(96).Within(0.02));
            foreach(var p in result.Mesh.Vertices)
                Assert.That(Math.Abs(Math.Abs(p.x)-2)<0.001||Math.Abs(Math.Abs(p.z)-1)<0.001,Is.True);
        }
        [Test]
        public void ThinLandTrianglesNearRoadDoNotCreateInternalWalls()
        {
            var land=Rect(0,0,0.0003f,1,10);var rest=Rect(0.0003f,0,1,1,10);
            int start=land.Vertices.Count;land.Vertices.AddRange(rest.Vertices);
            land.Triangles.AddRange(rest.Triangles.Select(i=>i+start));
            var result=GeoForgeRoadBanks.Build(land,new[]{Rect(-1,0,0,1,0)},new[]{Rect(-1,0,0,1,6)});
            Assert.That(Area(result.Mesh),Is.EqualTo(8).Within(0.01));
            Assert.That(result.MissingRoadSurfaceMeters,Is.LessThan(0.001));
        }
        [Test]
        public void LandEdgeTouchingOnlyARoadCornerIsNotAMissingRoadWall()
        {
            var land=new GeoForgeMeshData();
            land.Vertices.AddRange(new[]{new Vector3(-1,10,1),new Vector3(1,10,-1),new Vector3(-1,10,-1)});
            land.AddUpTriangle(0,1,2);
            var result=GeoForgeRoadBanks.Build(land,new[]{Rect(0,0,1,1,0)},new[]{Rect(0,0,1,1,6)});
            Assert.That(result.ExcludedNonRoadEdgeMeters,Is.GreaterThan(2.8));
            Assert.That(result.MissingRoadSurfaceMeters,Is.LessThan(0.001));
            Assert.That(Area(result.Mesh),Is.LessThan(0.01));
        }
        [Test]
        public void CrossingLandAndRoadHeightsDoNotMakeBowTieWalls()
        {
            var mask=Rect(-1,-1,1,1,0);var road=Rect(-1,-1,1,1,0);
            for(int i=0;i<road.Vertices.Count;i++){var p=road.Vertices[i];p.y=p.x;road.Vertices[i]=p;}
            var land=GeoForgeGroundCutout.Subtract(Rect(-5,-5,5,5,0),new[]{mask});
            var result=GeoForgeRoadBanks.Build(land,new[]{mask},new[]{road});
            Assert.That(Area(result.Mesh),Is.EqualTo(12).Within(0.01));
            Assert.That(result.MaximumHeightDifferenceMeters,Is.EqualTo(1).Within(0.001));
        }
        [Test]
        public void SlopingEdgesFollowActualMeshesAndMissingCoverageIsReported()
        {
            var mask=Rect(-1,-1,1,1,0);var road=Rect(-1,-1,1,1,6);
            for(int i=0;i<road.Vertices.Count;i++){var p=road.Vertices[i];p.y+=0.2f*p.x+0.1f*p.z;road.Vertices[i]=p;}
            var land=GeoForgeGroundCutout.Subtract(Rect(-5,-5,5,5,10),new[]{mask});
            var result=GeoForgeRoadBanks.Build(land,new[]{mask},new[]{road});
            foreach(var p in result.Mesh.Vertices)
                Assert.That(Math.Abs(p.y-10)<0.0001||Math.Abs(p.y-(6+0.2*p.x+0.1*p.z))<0.0001,Is.True);
            var missing=GeoForgeRoadBanks.Build(land,new[]{mask},Array.Empty<GeoForgeMeshData>());
            Assert.That(missing.Mesh.Triangles,Is.Empty);
            Assert.That(missing.MissingRoadSurfaceMeters,Is.EqualTo(8).Within(0.001));
            Assert.That(GeoForgeRoadBanks.Build(new GeoForgeMeshData(),new[]{mask},new[]{road}).Mesh.Triangles,Is.Empty);
            Assert.Throws<ArgumentException>(()=>GeoForgeRoadBanks.Build(land,new[]{mask},new[]{road},3));
        }
        [Test]
        public void CoplanarRoadFragmentsMergeWithoutChangingWallArea()
        {
            var mask=Rect(-4,-1,4,1,0);
            var land=GeoForgeGroundCutout.Subtract(Rect(-5,-5,5,5,10),new[]{mask});
            var roads=Enumerable.Range(0,32).Select(i=>Rect(-4+i*0.25f,-1,-4+(i+1)*0.25f,1,6)).ToArray();
            var original=GeoForgeRoadBanks.Build(land,new[]{mask},roads,maximumHeightErrorMeters:0);
            var merged=GeoForgeRoadBanks.Build(land,new[]{mask},roads);
            Assert.That(merged.Mesh.Triangles.Count,Is.LessThan(original.Mesh.Triangles.Count/2));
            Assert.That(merged.MergedCapIntervals,Is.GreaterThan(0));
            Assert.That(Area(merged.Mesh),Is.EqualTo(Area(original.Mesh)).Within(0.001));
            Assert.That(merged.MissingRoadSurfaceMeters,Is.EqualTo(original.MissingRoadSurfaceMeters));
            Assert.That(merged.MaximumSimplificationErrorMeters,Is.LessThanOrEqualTo(0.0001));
            GeoForgeRoadBanks.Build(land,new[]{mask},roads,merged.Mesh.Triangles.Count/3);
            Assert.Throws<ArgumentException>(()=>GeoForgeRoadBanks.Build(land,new[]{mask},roads,
                merged.Mesh.Triangles.Count/3,maximumHeightErrorMeters:0));
        }
        [Test]
        public void SimplificationBoundsAllOriginalHeightsWithoutAccumulatingError()
        {
            var mask=Rect(-4,-1,4,1,0);
            var land=GeoForgeGroundCutout.Subtract(Rect(-5,-5,5,5,10),new[]{mask});
            var roads=Enumerable.Range(0,32).Select(i=>
            {
                var road=Rect(-4+i*0.25f,-1,-4+(i+1)*0.25f,1,6);
                for(int j=0;j<road.Vertices.Count;j++)
                {
                    var p=road.Vertices[j];p.y=6+0.00004f*p.x*p.x+(Math.Abs(p.x)<0.01?0.002f:0);road.Vertices[j]=p;
                }
                return road;
            }).ToArray();
            var original=GeoForgeRoadBanks.Build(land,new[]{mask},roads,maximumHeightErrorMeters:0);
            var merged=GeoForgeRoadBanks.Build(land,new[]{mask},roads);
            Assert.That(merged.MergedCapIntervals,Is.GreaterThan(0));
            Assert.That(merged.MaximumSimplificationErrorMeters,Is.LessThanOrEqualTo(0.0001+1e-12));
            for(int i=0;i<original.Mesh.Vertices.Count;i+=8)foreach(int corner in new[]{2,3})
            {
                var p=original.Mesh.Vertices[i+corner];double error=double.PositiveInfinity;
                for(int j=0;j<merged.Mesh.Vertices.Count;j+=8)
                {
                    var a=merged.Mesh.Vertices[j+3];var b=merged.Mesh.Vertices[j+2];
                    double dx=(double)b.x-a.x,dz=(double)b.z-a.z,l2=dx*dx+dz*dz;
                    double t=((p.x-a.x)*dx+(p.z-a.z)*dz)/l2;
                    if(t< -1e-5||t>1+1e-5||Math.Abs((p.x-a.x)*dz-(p.z-a.z)*dx)>0.00001*Math.Sqrt(l2))continue;
                    error=Math.Min(error,Math.Abs(p.y-(a.y+(b.y-a.y)*t)));
                }
                Assert.That(error,Is.LessThanOrEqualTo(0.00011),"Float output must retain the bounded original lower edge");
            }
        }
        [Test]
        public void MergingNeverBridgesAMissingRoadInterval()
        {
            var mask=Rect(-4,-1,4,1,0);
            var land=GeoForgeGroundCutout.Subtract(Rect(-5,-5,5,5,10),new[]{mask});
            var roads=new[]{Rect(-4,-1,-1,1,6),Rect(1,-1,4,1,6)};
            var original=GeoForgeRoadBanks.Build(land,new[]{mask},roads,maximumHeightErrorMeters:0);
            var result=GeoForgeRoadBanks.Build(land,new[]{mask},roads);
            Assert.That(result.MissingRoadSurfaceMeters,Is.EqualTo(original.MissingRoadSurfaceMeters).Within(1e-10));
            Assert.That(result.MissingRoadSurfaceMeters,Is.GreaterThan(3.99));
            var mesh=result.Mesh.ToMesh("bank gap");var go=new GameObject("bank gap collider");
            try
            {
                var collider=go.AddComponent<MeshCollider>();collider.sharedMesh=mesh;Physics.SyncTransforms();
                Assert.That(collider.Raycast(new Ray(new Vector3(0,8,0),Vector3.forward),out _,2),Is.False);
                Assert.That(collider.Raycast(new Ray(new Vector3(2,8,0),Vector3.forward),out _,2),Is.True);
            }
            finally{UnityEngine.Object.DestroyImmediate(go);UnityEngine.Object.DestroyImmediate(mesh);}
            Assert.Throws<ArgumentException>(()=>GeoForgeRoadBanks.Build(land,new[]{mask},roads,maximumHeightErrorMeters:double.NaN));
        }
    }
}
