using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeBuildingPartsTests
    {
        private static GeoForgeBuilding Part(string id,double left,double height,double bottom=0)
            =>new GeoForgeBuilding {id=id,parent_id="parent",building_type="yes",height=height,min_height=bottom,
                ground_height_m=2,footprint=GeoForgeTerrainTests.Rectangle(left,0,10,10)};
        [Test]
        public void PartsReplaceParentAndKeepRaisedPassageWithCollider()
        {
            var low=Part("low",0,8);var raised=Part("raised",10,20,5);
            var parent=new GeoForgeBuilding {id="parent",height=20,building_type="yes",footprint=GeoForgeTerrainTests.Rectangle(0,0,20,10),
                render_footprints=new List<GeoForgePolygon>(),parts=new List<GeoForgeBuilding>{low,raised}};
            var scene=GeoForgeTerrainTests.Slope();scene.terrain=null;scene.buildings.Add(parent);
            var root=new GameObject("parts-test");
            try
            {
                var generator=root.AddComponent<GeoForgeSceneGenerator>();generator.generateOnStart=false;generator.LoadedScene=scene;
                generator.GenerateLoadedScene();
                var group=root.transform.Find("GeoForgeGenerated/Buildings");
                Assert.That(group.childCount,Is.EqualTo(2));
                var volume=group.Find("raised");var mesh=volume.GetComponent<MeshFilter>().sharedMesh;
                Assert.That(mesh.vertices.Min(v=>v.y),Is.EqualTo(7));
                Assert.That(mesh.vertices.Max(v=>v.y),Is.EqualTo(22));
                Assert.That(volume.Find("Foundation"),Is.Null);
                Physics.SyncTransforms();
                Assert.That(Physics.Raycast(new Vector3(15,4,-2),Vector3.forward,15),Is.False);
                Assert.That(Physics.Raycast(new Vector3(15,10,-2),Vector3.forward,15),Is.True);
                generator.GenerateBuildings();Assert.That(root.transform.Find("GeoForgeGenerated/Buildings").childCount,Is.EqualTo(2));
                generator.ClearGeneratedScene();Assert.That(root.transform.Find("GeoForgeGenerated"),Is.Null);
            }
            finally {UnityEngine.Object.DestroyImmediate(root);}
        }
        [Test]
        public void ExplicitRoofHeightPreservesTotalHeight()
        {
            var b=Part("roof",0,20,5);b.resolved_tags=new Dictionary<string,string>{{"roof:shape","gabled"},{"roof:height","2"}};
            var mesh=GeoForgeRoofGenerator.Build(GeoForgeBuildingVolumes.Volume(b),out var shape);
            Assert.That(shape,Is.EqualTo("gabled"));Assert.That(mesh.Vertices.Max(v=>v.y),Is.EqualTo(15));
            Assert.That(mesh.Vertices.Any(v=>Math.Abs(v.y-13)<0.001),Is.True);
        }
        [Test]
        public void GroundEstimateControlsFoundationAudit()
        {
            var sampler=new GeoForgeTerrainSampler(GeoForgeTerrainTests.Slope());var b=Part("base",0,10);b.ground_height_m=0.5;
            var fit=GeoForgeGeometryQuality.Building(b,sampler,true,0.3f,12);
            Assert.That(fit.baseElevation,Is.EqualTo(0.5));Assert.That(fit.foundationDepth,Is.LessThanOrEqualTo(0.5));
        }
        [Test]
        public void PartialCoverageRendersOnlyRemainderAndPart()
        {
            var parent=new GeoForgeBuilding {id="parent",height=10,footprint=GeoForgeTerrainTests.Rectangle(0,0,20,10),
                render_footprints=new List<GeoForgePolygon>{GeoForgeTerrainTests.Rectangle(10,0,10,10)},parts=new List<GeoForgeBuilding>{Part("part",0,12)}};
            var volumes=GeoForgeBuildingVolumes.Expand(new List<GeoForgeBuilding>{parent});
            Assert.That(volumes.Count,Is.EqualTo(2));Assert.That(volumes[0].footprint.exterior[0][0],Is.EqualTo(10));
            Assert.That(volumes[1].id,Is.EqualTo("part"));
        }
    }
}
