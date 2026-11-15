using System;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeElevationRegressionTests
    {
        [Test]
        public void QuarterEdgeVariationCannotHideBetweenMidpointProbes()
        {
            var source=new GeoForgeMeshData();
            source.Vertices.AddRange(new[]{new Vector3(0,0,0),new Vector3(4,0,0),new Vector3(0,0,4)});
            source.AddUpTriangle(0,1,2);
            var profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{0d,0d,0d},new[]{4d,0d,0d}}};
            Func<float,float,float> height=(x,z)=>(float)(0.08*Math.Exp(-((x-1)*(x-1)+z*z)/0.04));
            var result=GeoForgeRoadProfileSurface.Build(source,profile,heightSampler:height);
            Assert.That(result.Vertices.Any(p=>Math.Abs(p.x-1)<0.000001&&Math.Abs(p.z)<0.000001&&p.y>0.079),Is.True);
        }
        [Test]
        public void LandCoverUsesWaterPolygonAndPreservesWaterIsland()
        {
            var green=new GeoForgeArea{area_type="green",polygon=GeoForgeTerrainTests.Rectangle(0,0,10,10)};
            var water=new GeoForgeArea{area_type="water",polygon=GeoForgeTerrainTests.Rectangle(2,2,6,6)};
            water.polygon.holes=new[]{GeoForgeTerrainTests.Rectangle(4,4,2,2).exterior};
            var result=GeoForgeAreaGenerator.RemoveWaterCover(GeoForgeAreaGenerator.Build(green),new[]{water});
            double area=0;
            for(int i=0;i<result.Triangles.Count;i+=3){var a=result.Vertices[result.Triangles[i]];var b=result.Vertices[result.Triangles[i+1]];var c=result.Vertices[result.Triangles[i+2]];area+=Math.Abs(Vector3.Cross(b-a,c-a).y)/2;}
            Assert.That(area,Is.EqualTo(68).Within(0.001));
            Assert.That(result.Vertices.All(v=>Math.Abs(v.y-0.015)<0.00001),Is.True);
            var empty=GeoForgeAreaGenerator.RemoveWaterCover(GeoForgeAreaGenerator.Build(green),new[]{new GeoForgeArea{area_type="water",polygon=green.polygon}});
            Assert.That(empty.Triangles,Is.Empty);
        }
    }
}

