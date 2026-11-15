using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeRoadbedTests
    {
        private static GeoForgeMeshData Rectangle(float halfWidth,float y)
        {
            var m=new GeoForgeMeshData();m.Vertices.AddRange(new[]{new Vector3(-halfWidth,y,0),new Vector3(halfWidth,y,0),new Vector3(halfWidth,y,10),new Vector3(-halfWidth,y,10)});
            m.AddUpTriangle(0,1,2);m.AddUpTriangle(0,2,3);return m;
        }
        private static GeoForgeRoad Road()=>new GeoForgeRoad{id="road",road_category="automotive",layer=0};
        private static GeoForgeRoadbed Bed(GeoForgeRoad road)=>new GeoForgeRoadbed(
            new Dictionary<GeoForgeRoad,GeoForgeMeshData>{{road,Rectangle(2,3)}},new GeoForgeRoadbedSettings());
        [Test]
        public void InteriorIsBelowActualRoadAndShoulderBlendsToOriginalTerrain()
        {
            var bed=Bed(Road());
            Assert.That(bed.Height(0,5,10,out _),Is.EqualTo(2.97).Within(1e-5));
            Assert.That(bed.Height(4,5,10,out _),Is.EqualTo(6.485).Within(1e-5));
            Assert.That(bed.Height(6,5,10,out bool affected),Is.EqualTo(10));Assert.That(affected,Is.False);
            Assert.That(bed.Height(5.999f,5,10,out _),Is.EqualTo(10).Within(1e-5));
        }
        [TestCase("bridge")][TestCase("tunnel")][TestCase("layer")][TestCase("pedestrian")]
        public void GradeSeparatedAndOrdinaryPathsDoNotConditionTerrain(string kind)
        {
            var r=Road();r.bridge=kind=="bridge";r.tunnel=kind=="tunnel";
            if(kind=="layer")r.layer=1;if(kind=="pedestrian")r.road_category="pedestrian";
            var bed=Bed(r);Assert.That(bed.EligibleRoads,Is.Zero);
            Assert.That(bed.Height(0,5,10,out _),Is.EqualTo(10));
        }
        [Test]
        public void DerivedMeshDoesNotModifyInputAndHasNoInteriorPokeThrough()
        {
            var source=Rectangle(6,10);var original=source.Vertices.ToArray();
            var derived=Bed(Road()).Condition(source);
            Assert.That(source.Vertices,Is.EqualTo(original));
            var interior=derived.Vertices.Where(p=>Mathf.Abs(p.x)<1.9f&&p.z>0.1f&&p.z<9.9f).ToArray();
            Assert.That(interior.Length,Is.GreaterThan(0));
            Assert.That(interior.All(p=>Mathf.Abs(p.y-2.97f)<0.01f),Is.True);
        }
        [Test]
        public void CrossingCorrectionIsLocalAndDoesNotMoveRoadSurface()
        {
            var r=Road();r.road_category="pedestrian";r.road_subtype="crossing";
            var road=Rectangle(2,3);var before=road.Vertices.ToArray();
            var bed=new GeoForgeRoadbed(new Dictionary<GeoForgeRoad,GeoForgeMeshData>{{r,road}},new GeoForgeRoadbedSettings());
            Assert.That(bed.Height(0,5,10,out _),Is.EqualTo(2.97).Within(1e-5));
            Assert.That(bed.Height(2.31f,5,10,out _),Is.EqualTo(10));
            Assert.That(road.Vertices,Is.EqualTo(before));
        }
    }
}
