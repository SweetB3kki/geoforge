using System;
using System.Collections.Generic;
using NUnit.Framework;

namespace GeoForge.Tests
{
    public sealed class GeoForgeNetworkAuthorityTests
    {
        private static GeoForgeRoad Road(string id,string end,double z,double height,int layer=0) => new GeoForgeRoad {
            id=id, road_category="automotive", width=6.4, layer=layer,
            path=new[]{new[]{0d,0d,0d},new[]{100d,z,0d}},
            node_ids=new List<string>{"junction",end},
            vertical_profile=new GeoForgeRoadVerticalProfile {
                points=new[]{new[]{0d,0d,0d},new[]{100d,z,height}}
            }
        };
        [Test]
        public void ConnectedRoadsUseSameFieldBeyondFormerJunctionRadius()
        {
            var a=Road("a","end-a",0,2);var b=Road("b","end-b",5,4);
            var c=Road("c","end-c",-80,-1);var list=new[]{a,b,c};
            var settings=new GeoForgeRoadGeometrySettings();
            var ah=GeoForgeRoadProfileSurface.ConnectedHeight(a,list,settings);
            var bh=GeoForgeRoadProfileSurface.ConnectedHeight(b,list,settings);
            foreach(float x in new[]{8.8f,33.33f,40f,65f})
                Assert.That(ah(x,1),Is.EqualTo(bh(x,1)).Within(0.000001));
            Assert.That(ah(0,0),Is.EqualTo(0).Within(0.000001));
            Assert.That(ah(100,0),Is.EqualTo(2).Within(0.000001));
        }
        [Test]
        public void BridgeAndOtherLayerCannotJoinGroundAuthority()
        {
            var ground=Road("a","a",0,2);var other=Road("b","b",0,90,1);
            var bridge=Road("c","c",0,80);bridge.bridge=true;
            var h=GeoForgeRoadProfileSurface.ConnectedHeight(ground,new[]{ground,other,bridge},new GeoForgeRoadGeometrySettings());
            Assert.That(h(50,2),Is.EqualTo(1).Within(0.000001));
        }
    }
}
