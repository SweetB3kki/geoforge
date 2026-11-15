using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Object = UnityEngine.Object;

namespace GeoForge.Tests
{
    public sealed class GeoForgeGeometryTests
    {
        private static double[][] Ring(params double[] xy) => Enumerable.Range(0,xy.Length/2).Select(i=>new[]{xy[2*i],xy[2*i+1],0d}).ToArray();
        private static GeoForgePolygon Square() => new GeoForgePolygon { exterior=Ring(0,0,10,0,10,10,0,10,0,0), holes=Array.Empty<double[][]>() };
        private static GeoForgeBuilding Building(GeoForgePolygon polygon, double height=12) => new GeoForgeBuilding { id="test",footprint=polygon,height=height,position=new[]{999d,999d,0d} };
        private static double RoofArea(GeoForgeMeshData mesh, float height)
        {
            double area = 0;
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var a=mesh.Vertices[mesh.Triangles[i]]; var b=mesh.Vertices[mesh.Triangles[i+1]]; var c=mesh.Vertices[mesh.Triangles[i+2]];
                if(a.y!=height || b.y!=height || c.y!=height) continue;
                var cross=Vector3.Cross(b-a,c-a); Assert.That(cross.y,Is.GreaterThan(0)); area+=cross.y/2;
            }
            return area;
        }
        [Test] public void CoordinateMapping()
        { Assert.That(GeoForgeCoordinateConverter.GeoForgeToUnity(10,20,30),Is.EqualTo(new Vector3(10,30,20))); }
        [Test] public void RectangleHeightAndAbsoluteCoordinates()
        {
            var data=GeoForgeBuildingGenerator.Build(Building(Square()));
            Assert.That(data.Vertices.Min(v=>v.x),Is.Zero); Assert.That(data.Vertices.Max(v=>v.x),Is.EqualTo(10));
            Assert.That(data.Vertices.Max(v=>v.y),Is.EqualTo(12)); Assert.That(RoofArea(data,12),Is.EqualTo(100).Within(1e-5));
            var mesh=data.ToMesh("rectangle");
            Assert.That(mesh.bounds.size,Is.EqualTo(new Vector3(10,12,10)));
            Assert.That(mesh.normals.Any(n=>n.y>0.99),Is.True);
            Object.DestroyImmediate(mesh);
        }
        [Test] public void ConcaveRoof()
        {
            var p=Square(); p.exterior=Ring(0,0,4,0,4,1,1,1,1,4,0,4,0,0);
            Assert.That(RoofArea(GeoForgeBuildingGenerator.Build(Building(p)),12),Is.EqualTo(7).Within(1e-5));
        }
        [Test] public void CourtyardIsOpenWithReversedWinding()
        {
            var p=Square(); p.exterior=p.exterior.Reverse().ToArray();
            p.holes=new[]{Ring(3,3,7,3,7,7,3,7,3,3)};
            var data=GeoForgeBuildingGenerator.Build(Building(p));
            Assert.That(RoofArea(data,12),Is.EqualTo(84).Within(1e-5));
            for(int i=0;i<data.Triangles.Count;i+=3)
            {
                var a=data.Vertices[data.Triangles[i]];var b=data.Vertices[data.Triangles[i+1]];var c=data.Vertices[data.Triangles[i+2]];
                if(a.y!=12||b.y!=12||c.y!=12) continue;
                var center=(a+b+c)/3;
                Assert.That(center.x>3 && center.x<7 && center.z>3 && center.z<7,Is.False);
            }
        }
        [Test] public void TinyBuilding()
        {
            var p=Square();p.exterior=Ring(0,0,0.001,0,0.001,0.001,0,0.001,0,0);
            Assert.That(RoofArea(GeoForgeBuildingGenerator.Build(Building(p)),12),Is.EqualTo(1e-6).Within(1e-9));
        }
        [Test] public void InvalidAndOutsideHoleRejected()
        {
            var p=Square();p.holes=new[]{Ring(20,20,21,20,21,21,20,21,20,20)};
            Assert.Throws<ArgumentException>(()=>GeoForgeBuildingGenerator.Build(Building(p)));
            Assert.Throws<ArgumentException>(()=>GeoForgeBuildingGenerator.Build(Building(Square(),-1)));
            p=Square();p.exterior=Ring(0,0,10,10,0,10,10,0,0,0);
            Assert.Throws<ArgumentException>(()=>GeoForgeBuildingGenerator.Build(Building(p)));
        }
        [Test] public void TwoPointRoadHasRequestedWidth()
        {
            var d=GeoForgeRoadGenerator.Build(new GeoForgeRoad {path=Ring(0,0,10,0),width=6});
            Assert.That(d.Vertices.Max(v=>v.z)-d.Vertices.Min(v=>v.z),Is.EqualTo(6));
            Assert.That(d.Vertices.All(v=>v.y==0.03f),Is.True);Assert.That(d.Triangles.Count,Is.EqualTo(6));
        }
        [Test] public void CurvedRoadAndDuplicatePoints()
        {
            var path=Enumerable.Range(0,100).Select(i=>new[]{(double)i,Math.Sin(i/10d)*20,0d}).ToList();path.Insert(2,path[1]);
            var d=GeoForgeRoadGenerator.Build(new GeoForgeRoad{path=path.ToArray(),width=4});
            Assert.That(d.Triangles.Count,Is.GreaterThan(500));
            Assert.That(d.Vertices.All(v=>!float.IsNaN(v.x)&&!float.IsNaN(v.z)),Is.True);
        }
        [TestCase("water",0.01f)] [TestCase("green",0.015f)]
        public void AreaWithHole(string type,float y)
        {
            var p=Square();p.holes=new[]{Ring(3,3,7,3,7,7,3,7,3,3)};
            var d=GeoForgeAreaGenerator.Build(new GeoForgeArea{polygon=p,area_type=type});
            Assert.That(RoofArea(d,y),Is.EqualTo(84).Within(1e-5));
        }
        private const string EmptyJson="{\"metadata\":{\"schema_version\":\"1.0\",\"units\":\"meters\",\"axes\":\"X=east,Y=north,Z=up\"},\"buildings\":[],\"roads\":[],\"water_areas\":[],\"green_areas\":[]}";
        [Test] public void LoaderValidatesSchemaAndContract()
        {
            Assert.Throws<InvalidDataException>(()=>GeoForgeJsonLoader.Parse(EmptyJson.Replace("1.0","2.0")));
            Assert.Throws<InvalidDataException>(()=>GeoForgeJsonLoader.Parse(EmptyJson.Replace("meters","feet")));
            Assert.Throws<Newtonsoft.Json.JsonReaderException>(()=>GeoForgeJsonLoader.Parse("bad json"));
        }
        [Test] public void ClearRepeatEmptyAndInvalidObject()
        {
            var go=new GameObject("test generator");
            try
            {
                var generator=go.AddComponent<GeoForgeSceneGenerator>();generator.LoadedScene=GeoForgeJsonLoader.Parse(EmptyJson);
                generator.GenerateLoadedScene();Assert.That(generator.LastStatistics.vertices,Is.Zero);
                generator.LoadedScene.buildings.Add(Building(Square()));
                generator.LoadedScene.buildings.Add(Building(Square(),-1));
                for(int i=0;i<2;i++)
                {
                    LogAssert.Expect(LogType.Warning,new Regex("failed Buildings object 'test'"));
                    generator.GenerateLoadedScene();
                    Assert.That(generator.LastStatistics.buildings,Is.EqualTo(1));Assert.That(generator.LastStatistics.buildingsFailed,Is.EqualTo(1));
                    Assert.That(go.transform.childCount,Is.EqualTo(1));Assert.That(go.GetComponentsInChildren<MeshFilter>().Length,Is.EqualTo(1));
                }
                generator.ClearGeneratedScene();Assert.That(go.transform.childCount,Is.Zero);
            }
            finally { Object.DestroyImmediate(go); }
        }
        [Test] public void MalformedFeatureDoesNotAbortDeserialization()
        {
            LogAssert.Expect(LogType.Warning,new Regex("invalid buildings object broken"));
            var scene=GeoForgeJsonLoader.Parse(EmptyJson.Replace("\"buildings\":[]","\"buildings\":[{\"id\":\"broken\",\"height\":\"oops\"}]"));
            Assert.That(scene.buildings.Count,Is.EqualTo(1));Assert.That(scene.buildings[0],Is.Null);
        }
        [TestCase("../../output/scene.json",551,133,0,10)]
        [TestCase("../../output/water-example/scene.json",414,1299,3,148)]
        public void ExistingScenesGenerate(string path,int buildings,int roads,int water,int green)
        {
            var go=new GameObject("integration");
            try
            {
                var generator=go.AddComponent<GeoForgeSceneGenerator>();generator.sceneJsonPath=path;generator.GenerateScene();
                var s=generator.LastStatistics;Assert.That(s,Is.Not.Null);
                Assert.That(s.buildings,Is.EqualTo(buildings));Assert.That(s.roads,Is.EqualTo(roads));
                Assert.That(s.water,Is.EqualTo(water));Assert.That(s.green,Is.EqualTo(green));
                Assert.That(s.buildingsFailed+s.roadsFailed+s.waterFailed+s.greenFailed,Is.Zero);
                Assert.That(s.triangles,Is.GreaterThan(0));
            }
            finally { Object.DestroyImmediate(go); }
        }
    }
}
