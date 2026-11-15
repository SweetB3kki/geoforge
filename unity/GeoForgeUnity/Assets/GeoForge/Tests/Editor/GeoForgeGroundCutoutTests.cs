using System;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeGroundCutoutTests
    {
        private static GeoForgeMeshData Rectangle(float x0, float z0, float x1, float z1, float y=0)
        {
            var mesh = new GeoForgeMeshData();
            mesh.Vertices.AddRange(new[] {new Vector3(x0,y,z0),new Vector3(x1,y,z0),new Vector3(x1,y,z1),new Vector3(x0,y,z1)});
            mesh.AddUpTriangle(0,1,2); mesh.AddUpTriangle(0,2,3); return mesh;
        }
        private static double Area(GeoForgeMeshData mesh)
        {
            double sum=0;
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var a=mesh.Vertices[mesh.Triangles[i]];
                var b=mesh.Vertices[mesh.Triangles[i+1]];
                var c=mesh.Vertices[mesh.Triangles[i+2]];
                sum+=Math.Abs(Vector3.Cross(b-a,c-a).y)/2;
            }
            return sum;
        }
        [Test]
        public void OverlappingMasksRemoveUnionOnceAndLeaveInputsUnchanged()
        {
            var ground=Rectangle(0,0,10,10);
            var first=Rectangle(2,-2,4,12,7);var second=Rectangle(3,-2,5,12,-4);
            var saved=ground.Vertices.ToArray();var indices=ground.Triangles.ToArray();
            var result=GeoForgeGroundCutout.Subtract(ground,new[]{first,second});
            Assert.That(Area(result),Is.EqualTo(70).Within(0.0001));
            CollectionAssert.AreEqual(saved,ground.Vertices);CollectionAssert.AreEqual(indices,ground.Triangles);
            Assert.That(first.Vertices.All(v=>v.y==7));Assert.That(second.Vertices.All(v=>v.y==-4));
        }
        [Test]
        public void InteriorCutoutLeavesAHoleAndExteriorMaskDoesNotAddLand()
        {
            var ground=Rectangle(0,0,10,10);
            var result=GeoForgeGroundCutout.Subtract(ground,new[]{Rectangle(2,2,8,8),Rectangle(20,20,30,30)});
            Assert.That(Area(result),Is.EqualTo(64).Within(0.0001));
        }
        [Test]
        public void ReplacementColliderCanBeBelowRawGroundWithoutHiddenRawCollider()
        {
            var ground=GeoForgeGroundCutout.Subtract(Rectangle(0,0,10,10,10),new[]{Rectangle(4,0,6,10)});
            var terrain=new GameObject("derived terrain");var road=new GameObject("conditioned road");
            var terrainMesh=ground.ToMesh("terrain cutout");var roadMesh=Rectangle(4,0,6,10,6).ToMesh("road");
            try
            {
                var tc=terrain.AddComponent<MeshCollider>();tc.sharedMesh=terrainMesh;
                var rc=road.AddComponent<MeshCollider>();rc.sharedMesh=roadMesh;
                Physics.SyncTransforms();
                var overRoad=new Ray(new Vector3(5,20,5),Vector3.down);
                Assert.That(tc.Raycast(overRoad,out _,30),Is.False,"Raw terrain must not block the replacement road.");
                Assert.That(rc.Raycast(overRoad,out var hit,30),Is.True);
                Assert.That(hit.point.y,Is.EqualTo(6).Within(0.001));
                Assert.That(tc.Raycast(new Ray(new Vector3(2,20,5),Vector3.down),out hit,30),Is.True);
                Assert.That(hit.point.y,Is.EqualTo(10).Within(0.001),"Outside the corridor the original elevation remains.");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(terrain);UnityEngine.Object.DestroyImmediate(road);
                UnityEngine.Object.DestroyImmediate(terrainMesh);UnityEngine.Object.DestroyImmediate(roadMesh);
            }
        }
        [Test]
        public void FloatClippingSliversAreRemovedButMillimetreFeaturesRemain()
        {
            var source=new GeoForgeMeshData();
            // Two observed failure shapes: almost coincident vertices and an
            // almost collinear third vertex at metre-scale local coordinates.
            source.Vertices.AddRange(new[]{
                new Vector3(187.9075f,0,256.355225f),new Vector3(187.907486f,0,256.355225f),new Vector3(187.690338f,0,256.635254f),
                new Vector3(-255.468979f,0,51.5379753f),new Vector3(-257.2209f,0,53.4004173f),new Vector3(-256.8393f,0,52.99476f)});
            source.AddUpTriangle(0,1,2);source.AddUpTriangle(3,4,5);
            var saved=source.Vertices.ToArray();
            Assert.That(GeoForgeGroundCutout.Subtract(source,Array.Empty<GeoForgeMeshData>()).Triangles,Is.Empty);
            CollectionAssert.AreEqual(saved,source.Vertices);
            var narrow=Rectangle(0,0,1,0.002f);
            var kept=GeoForgeGroundCutout.Subtract(narrow,Array.Empty<GeoForgeMeshData>());
            Assert.That(Area(kept),Is.EqualTo(0.002).Within(0.000001));
        }
        [Test]
        public void FullCoverageProducesAnExplicitEmptySurfaceAndBudgetIsBounded()
        {
            var ground=Rectangle(0,0,10,10);
            Assert.That(GeoForgeGroundCutout.Subtract(ground,new[]{Rectangle(-1,-1,11,11)}).Triangles,Is.Empty);
            Assert.Throws<ArgumentException>(()=>GeoForgeGroundCutout.Subtract(ground,new[]{ground},1));
        }
        [Test]
        public void LocalCutoutPreservesSlopingSourcePlanes()
        {
            var source=Rectangle(0,0,10,10);
            for(int i=0;i<source.Vertices.Count;i++)
            {var p=source.Vertices[i];p.y=0.1f*p.x+0.2f*p.z;source.Vertices[i]=p;}
            var clipped=GeoForgeGroundCutout.SubtractPreservingPlanes(source,new[]{Rectangle(4,-1,6,11)});
            Assert.That(Area(clipped),Is.EqualTo(80).Within(0.001));
            foreach(var p in clipped.Vertices)Assert.That(p.y,Is.EqualTo(0.1f*p.x+0.2f*p.z).Within(0.00001));
        }
        [Test]
        public void SceneGenerationUsesReplacementCollisionAndFilterRestoresTerrain()
        {
            var scene=GeoForgeTerrainTests.Slope();
            scene.roads.Add(new GeoForgeRoad{id="profiled",road_type="primary",width=2,
                path=new[]{new[]{1d,5d,0d},new[]{9d,5d,0d}},
                vertical_profile=new GeoForgeRoadVerticalProfile{
                    points=new[]{new[]{1d,5d,-1d},new[]{9d,5d,-1d}},surface_visible=true}});
            var saved=scene.terrain.heights.ToArray();var owner=new GameObject("profile integration");
            try
            {
                var generator=owner.AddComponent<GeoForgeSceneGenerator>();generator.LoadedScene=scene;
                generator.GenerateLoadedScene();Physics.SyncTransforms();
                var root=owner.transform.Find("GeoForgeGenerated");
                var tc=root.Find("Terrain").GetComponent<MeshCollider>();
                var rc=root.Find("Roads/profiled").GetComponent<MeshCollider>();
                var ray=new Ray(new Vector3(5,20,5),Vector3.down);
                Assert.That(tc.Raycast(ray,out _,30),Is.False);
                Assert.That(rc.Raycast(ray,out var hit,30),Is.True);
                Assert.That(hit.point.y,Is.EqualTo(-0.97f).Within(0.001));
                var bank=root.Find("Terrain/RoadBanks");
                Assert.That(bank,Is.Not.Null);
                var bankCollider=bank.GetComponent<MeshCollider>();
                Assert.That(bankCollider.Raycast(new Ray(new Vector3(5,0,5),Vector3.forward),out var bankHit,3),Is.True);
                Assert.That(bankHit.point.z,Is.EqualTo(6).Within(0.001));
                CollectionAssert.AreEqual(saved,scene.terrain.heights);
                generator.ShowAutomotiveRoads=false;generator.GenerateRoads();Physics.SyncTransforms();
                tc=root.Find("Terrain").GetComponent<MeshCollider>();
                Assert.That(tc.Raycast(ray,out hit,30),Is.True);
                Assert.That(hit.point.y,Is.EqualTo(1.5f).Within(0.001));
                Assert.That(generator.LastStatistics.roads,Is.Zero);
                Assert.That(root.Find("Terrain/RoadBanks"),Is.Null);
            }
            finally{UnityEngine.Object.DestroyImmediate(owner);}
        }
    }
}
