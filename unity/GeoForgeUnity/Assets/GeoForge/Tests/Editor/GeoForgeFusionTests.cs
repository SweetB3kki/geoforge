using System;
using System.Collections.Generic;
using NUnit.Framework;

namespace GeoForge.Tests
{
    public sealed class GeoForgeFusionTests
    {
        [Test]
        public void ResolvedStyleWinsWithoutMutatingRawTags()
        {
            var b=new GeoForgeBuilding {source_tags=new Dictionary<string,string>{{"roof:shape","flat"}},
                resolved_tags=new Dictionary<string,string>{{"roof:shape","gabled"},{"building:colour","#FF8800"}}};
            Assert.That(GeoForgeBuildingStyleResolver.Tag(b,"roof:shape"),Is.EqualTo("gabled"));
            Assert.That(b.source_tags["roof:shape"],Is.EqualTo("flat"));
            Assert.That(GeoForgeBuildingStyleResolver.Wall(b).g,Is.EqualTo(136f/255).Within(0.001));
            b.resolved_tags=null;
            Assert.That(GeoForgeBuildingStyleResolver.Tag(b,"roof:shape"),Is.EqualTo("flat"));
        }
        [Test]
        public void ExplicitWaterLevelOverridesTerrainMedian()
        {
            var sampler=new GeoForgeTerrainSampler(GeoForgeTerrainTests.Slope());
            var area=new GeoForgeArea {polygon=GeoForgeTerrainTests.Rectangle(0,0,10,10),water_level_m=-32.312};
            Assert.That(GeoForgeWaterLevel.Resolve(area,sampler),Is.EqualTo(-32.312f).Within(0.0001));
            area.water_level_m=null;
            Assert.That(GeoForgeWaterLevel.Resolve(area,sampler),Is.EqualTo(sampler.PolygonHeight(area.polygon,true)));
        }
        [TestCase(double.NaN)][TestCase(double.PositiveInfinity)][TestCase(100001d)]
        public void InvalidExplicitWaterLevelFails(double level)
        {
            var area=new GeoForgeArea {water_level_m=level};
            Assert.Throws<ArgumentException>(()=>GeoForgeWaterLevel.Resolve(area,null));
        }
    }
}
