using System.Collections.Generic;
using NUnit.Framework;
using UnityEngine;
namespace GeoForge.Tests
{
    public sealed class GeoForgeCrossingElevationTests
    {
        [TestCase(false,false,0,true)]
        [TestCase(true,false,0,false)]
        [TestCase(false,true,0,false)]
        [TestCase(false,false,1,false)]
        public void OnlyCompatibleGroundCrossingInheritsActualRoadPlane(bool bridge,bool tunnel,int layer,bool inherits)
        {
            var road=new GeoForgeRoad{id="road",road_category="automotive",layer=0};
            var mesh=new GeoForgeMeshData();
            mesh.Vertices.AddRange(new[]{new Vector3(0,7,0),new Vector3(10,9,0),new Vector3(0,7,10)});
            mesh.AddUpTriangle(0,1,2);
            var crossing=new GeoForgeRoad{id="cross",road_category="pedestrian",road_subtype="crossing",layer=layer,
                bridge=bridge,tunnel=tunnel,vertical_profile=new GeoForgeRoadVerticalProfile {
                    points=new[]{new[]{0d,0d,1d},new[]{10d,0d,1d}}
                }};
            var settings=new GeoForgeRoadGeometrySettings();
            var sampler=GeoForgeCrossingElevation.Create(crossing,new Dictionary<GeoForgeRoad,GeoForgeMeshData>{{road,mesh}},settings);
            float flatOffset=GeoForgeRoadNetworkBuilder.Elevation(crossing,settings);
            Assert.That(sampler(2,2),Is.EqualTo(inherits?7.405-flatOffset:1).Within(0.00001));
            Assert.That(sampler(100,100),Is.EqualTo(1).Within(0.00001));
        }
    }
}
