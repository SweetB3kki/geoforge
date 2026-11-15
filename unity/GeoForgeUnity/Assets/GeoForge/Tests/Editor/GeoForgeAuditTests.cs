using NUnit.Framework;
using UnityEngine;
using System.Linq;

namespace GeoForge.Tests
{
    public sealed class GeoForgeAuditTests
    {
        [Test] public void FoundationClosesGapPreservesRigidBodyAndHasCollider()
        {
            var scene=GeoForgeTerrainTests.Slope();
            scene.buildings.Add(new GeoForgeBuilding{id="slope-house",height=5,footprint=GeoForgeTerrainTests.Rectangle(1,1,7,7)});
            var root=new GameObject("foundation test");
            try
            {
                var g=root.AddComponent<GeoForgeSceneGenerator>();g.LoadedScene=scene;g.GenerateLoadedScene();
                var fit=g.BuildingAudit.Single();Assert.That(fit.foundationDepth,Is.GreaterThan(0));Assert.That(fit.remainingGap,Is.Zero.Within(0.001));Assert.That(fit.maximumPenetration,Is.GreaterThan(0));
                var building=root.transform.Find("GeoForgeGenerated/Buildings/slope-house");var f=building.Find("Foundation");Assert.That(f.GetComponent<MeshCollider>(),Is.Not.Null);
                Assert.That(building.GetComponent<MeshFilter>().sharedMesh.bounds.size.y,Is.EqualTo(5).Within(0.001));
                Assert.That(f.GetComponent<MeshFilter>().sharedMesh.bounds.min.y,Is.EqualTo(fit.minimumTerrainUnderFootprint).Within(0.001));
                g.GenerateLoadedScene();Assert.That(root.GetComponentsInChildren<MeshFilter>().Count(x=>x.name=="Foundation"),Is.EqualTo(1));
                g.ClearGeneratedScene();Assert.That(root.GetComponentsInChildren<Collider>(),Is.Empty);
            }
            finally{Object.DestroyImmediate(root);}
        }
        [Test] public void FoundationDepthCapReportsResidualGap()
        {
            var scene=GeoForgeTerrainTests.Slope();var b=new GeoForgeBuilding{id="b",height=5,footprint=GeoForgeTerrainTests.Rectangle(1,1,7,7)};
            var q=GeoForgeGeometryQuality.Building(b,new GeoForgeTerrainSampler(scene),true,0.1f,0.2f);
            Assert.That(q.foundationDepth,Is.EqualTo(0.2f));Assert.That(q.remainingGap,Is.GreaterThan(0));
        }
        private static GeoForgeMeshData Overlay()
        {var s=new GeoForgeMeshData();s.Vertices.AddRange(new[]{new Vector3(0,0.03f,0),new Vector3(10,0.03f,0),new Vector3(10,0.03f,10),new Vector3(0,0.03f,10)});s.AddUpTriangle(0,1,2);s.AddUpTriangle(0,2,3);return s;}
        [Test] public void AdaptiveRefinesCurvatureButNotPlanarSlope()
        {
            var scene=GeoForgeTerrainTests.Slope();var settings=new GeoForgeConformSettings();
            var flat=GeoForgeAdaptiveSurface.Build(Overlay(),new GeoForgeTerrainSampler(scene),settings,out int limits);
            Assert.That(flat.Triangles.Count,Is.EqualTo(6));Assert.That(limits,Is.Zero);
            scene.terrain.heights=new[]{0d,0,0,0,4,0,0,0,0};var sampler=new GeoForgeTerrainSampler(scene);
            var mesh=GeoForgeAdaptiveSurface.Build(Overlay(),sampler,settings,out limits);
            Assert.That(mesh.Triangles.Count,Is.GreaterThan(6));
            var q=GeoForgeGeometryQuality.Surface("r","road",mesh,sampler,0.03f,0.021f);
            Assert.That(q.maxTerrainErrorMeters,Is.LessThanOrEqualTo(0.021f));Assert.That(q.degenerateTriangles,Is.Zero);
        }
        [TestCase(false)] [TestCase(true)] public void AdaptiveBudgetAndDepthLimitsAreReported(bool exactFallback)
        {
            var scene=GeoForgeTerrainTests.Slope();scene.terrain.heights=new[]{0d,0,0,0,4,0,0,0,0};var sampler=new GeoForgeTerrainSampler(scene);
            var s=new GeoForgeConformSettings {exactFallback=exactFallback,maximumGeneratedTrianglesPerObject=3,maximumSubdivisionDepth=1};
            var mesh=GeoForgeAdaptiveSurface.Build(Overlay(),sampler,s,out int limits);
            Assert.That(mesh.Triangles.Count/3,Is.LessThanOrEqualTo(3));Assert.That(limits,Is.GreaterThan(0));
        }
        [Test] public void FullIntersectionCheckFindsInteriorDeviation()
        {
            var scene=GeoForgeTerrainTests.Slope();scene.terrain.heights=new[]{0d,0,0,0,4,0,0,0,0};
            var sampler=new GeoForgeTerrainSampler(scene);
            Assert.That(sampler.ConformsEverywhere(Overlay(),0.03f,0.02f,10000),Is.False);
            Assert.That(sampler.ConformsEverywhere(sampler.Drape(Overlay()),0.03f,0.001f,10000),Is.True);
        }
    }
}
