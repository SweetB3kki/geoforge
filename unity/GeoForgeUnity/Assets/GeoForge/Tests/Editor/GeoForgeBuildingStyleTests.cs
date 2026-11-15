using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeBuildingStyleTests
    {
        [TestCase("#F80")][TestCase("#FF8800")][TestCase("beige")][TestCase("grey")]
        public void Colours(string input){Assert.That(GeoForgeBuildingStyleResolver.TryColour(input,out var color),Is.True);Assert.That(color.a,Is.EqualTo(1));}
        [TestCase("#XYZ")][TestCase("red;blue")][TestCase("")]
        public void InvalidColoursFallback(string input){Assert.That(GeoForgeBuildingStyleResolver.TryColour(input,out _),Is.False);}
        [TestCase("flat")][TestCase("gabled")][TestCase("hipped")]
        public void RoofPreservesTotalHeightAndSupportsSeparateMaterial(string shape)
        {
            var b=new GeoForgeBuilding{id="roof",height=12,building_type="house",footprint=GeoForgeTerrainTests.Rectangle(0,0,20,10),
                source_tags=new Dictionary<string,string>{{"roof:shape",shape}}};
            var mesh=GeoForgeRoofGenerator.Build(b,out var actual);Assert.That(actual,Is.EqualTo(shape));
            Assert.That(mesh.Vertices.Max(v=>v.y),Is.EqualTo(12));Assert.That(mesh.Vertices.Min(v=>v.y),Is.Zero);
            Assert.That(mesh.RoofTriangleIndexCount,Is.GreaterThan(0));
            var native=mesh.ToMesh("roof");try{Assert.That(native.subMeshCount,Is.EqualTo(2));}finally{Object.DestroyImmediate(native);}
        }
        [Test]
        public void CourtyardRoofFallsBackAndStylesDiffer()
        {
            var b=new GeoForgeBuilding{id="courtyard",height=12,building_type="house",footprint=GeoForgeTerrainTests.Rectangle(0,0,20,20),
                source_tags=new Dictionary<string,string>{{"roof:shape","hipped"}}};
            b.footprint.holes=new[]{GeoForgeTerrainTests.Rectangle(5,5,5,5).exterior};
            GeoForgeRoofGenerator.Build(b,out var shape);Assert.That(shape,Is.EqualTo("flat"));
            var residential=GeoForgeBuildingStyleResolver.Wall(b);b.building_type="warehouse";
            Assert.That(GeoForgeBuildingStyleResolver.Wall(b),Is.Not.EqualTo(residential));
            b.source_tags["building:colour"]="#FF8800";
            Assert.That(GeoForgeBuildingStyleResolver.Wall(b).g,Is.EqualTo(136f/255).Within(0.001));
        }
    }
}
