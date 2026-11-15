using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeRoadGeometryTests
    {
        private static GeoForgeRoad Road(string id, double width, string type, params double[] xy)
        {
            return new GeoForgeRoad {id=id, width=width, road_type=type, road_category=type=="footway" ? "pedestrian" : "automotive",
                path=Enumerable.Range(0,xy.Length/2).Select(i=>new[]{xy[i*2],xy[i*2+1],0d}).ToArray()};
        }
        private static GeoForgeRoadNetworkBuilder.Result Build(params GeoForgeRoad[] roads)
            => GeoForgeRoadGenerator.BuildNetwork(roads,new GeoForgeRoadGeometrySettings());
        private static void Valid(GeoForgeRoadNetworkBuilder.Result result)
        {
            Assert.That(result.Errors,Is.Empty);
            foreach(var mesh in result.Meshes.Values)
            {
                Assert.That(mesh.Triangles.Count,Is.GreaterThan(0));
                Assert.That(mesh.Vertices.All(p=>!float.IsNaN(p.x)&&!float.IsNaN(p.y)&&!float.IsNaN(p.z)),Is.True);
                for(int i=0;i<mesh.Triangles.Count;i+=3)
                {
                    var a=mesh.Vertices[mesh.Triangles[i]];var b=mesh.Vertices[mesh.Triangles[i+1]];var c=mesh.Vertices[mesh.Triangles[i+2]];
                    Assert.That(Vector3.Cross(b-a,c-a).y,Is.GreaterThan(0));
                }
            }
        }
        [TestCase(12,6)] [TestCase(6,12)]
        public void WidthTransitionIsContinuousAndLimited(double first,double second)
        {
            var a=Road("a",first,"primary",-20,0,0,0);var b=Road("b",second,"primary",0,0,20,0);
            var result=Build(a,b); Valid(result);
            Assert.That(result.Transitions.Count,Is.EqualTo(1));Assert.That(result.Junctions,Is.Empty);
            var seamA=result.Mesh(a).Vertices.Where(v=>Math.Abs(v.x)<0.001).Select(v=>v.z).OrderBy(v=>v).ToArray();
            var seamB=result.Mesh(b).Vertices.Where(v=>Math.Abs(v.x)<0.001).Select(v=>v.z).OrderBy(v=>v).ToArray();
            Assert.That(seamA,Is.EqualTo(seamB));Assert.That(seamA.Last()-seamA.First(),Is.EqualTo((first+second)/2).Within(0.001));
            Assert.That(result.Mesh(a).Vertices.Any(v=>Math.Abs(v.x+8)<0.001 && Math.Abs(v.z-first/2)<0.001),Is.True);
            Assert.That(result.Mesh(b).Vertices.Any(v=>Math.Abs(v.x-8)<0.001 && Math.Abs(v.z-second/2)<0.001),Is.True);
            Assert.That(a.width,Is.EqualTo(first));Assert.That(a.path.Length,Is.EqualTo(2));
        }
        [TestCase("primary","primary_link")]
        [TestCase("residential","service")]
        [TestCase("primary","secondary")]
        [TestCase("secondary","tertiary")]
        [TestCase("tertiary","residential")]
        [TestCase("motorway","motorway_link")]
        [TestCase("trunk","trunk_link")]
        public void CompatibleClassesTaperWithoutMerging(string first,string second)
        {
            var result=Build(Road("a",12,first,-30,0,0,0),Road("b",6,second,0,0,30,0));
            Valid(result);Assert.That(result.Transitions.Count,Is.EqualTo(1));Assert.That(result.Meshes.Count,Is.EqualTo(2));
        }
        [TestCase("T")] [TestCase("X")] [TestCase("Y")]
        public void JunctionPatchClosesAllTrimmedMouths(string shape)
        {
            var roads=new List<GeoForgeRoad>();
            if(shape=="Y")
            {
                roads.Add(Road("a",6,"primary",0,0,0,-30));roads.Add(Road("b",6,"primary",0,0,-20,25));roads.Add(Road("c",6,"primary",0,0,20,25));
            }
            else
            {
                // Shared interior OSM vertex must contribute two arms.
                roads.Add(Road("a",6,"primary",-30,0,0,0,30,0));
                roads.Add(shape=="X" ? Road("b",6,"primary",0,-30,0,0,0,30) : Road("b",6,"primary",0,0,0,30));
            }
            var result=Build(roads.ToArray());Valid(result);
            Assert.That(result.Junctions.Count,Is.EqualTo(1));Assert.That(result.Transitions,Is.Empty);
            var j=result.Junctions.Single();Assert.That(j.ConnectedRoadIds.Count,Is.EqualTo(shape=="X"?4:3));
            Assert.That(j.Polygon.Count,Is.GreaterThanOrEqualTo(4));
            foreach(var direction in j.ConnectedDirections)
            {
                var side=new Vector3(-direction.z,0,direction.x)*3;
                var mouth=j.Position+direction*4.4f;
                Assert.That(j.Polygon.Any(p=>Vector3.Distance(p,mouth+side)<0.001f),Is.True);
                Assert.That(j.Polygon.Any(p=>Vector3.Distance(p,mouth-side)<0.001f),Is.True);
            }
        }
        [Test]
        public void AngledTwoRoadsUsePatchInsteadOfTaper()
        {
            var result=Build(Road("a",6,"residential",-20,0,0,0),Road("b",4,"service",0,0,0,20));
            Valid(result);Assert.That(result.Junctions.Count,Is.EqualTo(1));Assert.That(result.Transitions,Is.Empty);
        }
        [TestCase("footway","pedestrian")][TestCase("cycleway","cycle")][TestCase("steps","steps")]
        public void PathsNeverAffectAutomotiveGeometry(string type,string category)
        {
            var a=Road("a",12,"primary",-20,0,0,0);var b=Road("b",2,type,0,0,20,0);b.road_category=category;b.road_subtype="crossing";
            var result=Build(a,b);Valid(result);Assert.That(result.Transitions,Is.Empty);Assert.That(result.Junctions,Is.Empty);
            Assert.That(result.Mesh(a).Vertices.Max(v=>v.z),Is.EqualTo(6));
        }
        [TestCase("bridge")][TestCase("layer")][TestCase("tunnel")]
        public void StructureCrossingHasNoJunctionAndDifferentElevation(string structure)
        {
            var a=Road("a",6,"primary",-20,0,0,0,20,0);var b=Road("b",6,"primary",0,-20,0,0,0,20);
            b.bridge=structure=="bridge";b.tunnel=structure=="tunnel";if(structure=="layer")b.layer=1;
            var result=Build(a,b);Valid(result);Assert.That(result.Junctions,Is.Empty);Assert.That(result.Transitions,Is.Empty);
            Assert.That(result.LayerSeparatedRoads,Is.EqualTo(1));Assert.That(result.Mesh(a).Vertices[0].y,Is.Not.EqualTo(result.Mesh(b).Vertices[0].y));
        }
        [Test]
        public void GeometricCrossingWithoutSharedVertexHasNoJunction()
        {
            var result=Build(Road("a",6,"primary",-20,0,20,0),Road("b",6,"primary",0,-20,0,20));
            Valid(result);Assert.That(result.Junctions,Is.Empty);
        }
        [Test]
        public void ParallelOnewayCarriagewaysStayIndependent()
        {
            var a=Road("a",6,"primary",-20,0,20,0);var b=Road("b",6,"primary",-20,8,20,8);a.oneway=b.oneway=1;
            var result=Build(a,b);Valid(result);Assert.That(result.Junctions,Is.Empty);Assert.That(result.Transitions,Is.Empty);
            Assert.That(result.Mesh(a).Vertices.Max(v=>v.z),Is.LessThan(result.Mesh(b).Vertices.Min(v=>v.z)));
        }
        [Test]
        public void ExplicitDistinctTopologyIdsAreNotJoined()
        {
            var a=Road("a",6,"primary",-20,0,0,0);var b=Road("b",12,"primary",0,0,20,0);
            a.node_ids=new List<string>{"a0","a1"};b.node_ids=new List<string>{"b0","b1"};
            var result=Build(a,b);Valid(result);Assert.That(result.Transitions,Is.Empty);Assert.That(result.Junctions,Is.Empty);
        }
        [Test]
        public void TinySegmentIsPreservedAndTransitionDoesNotOvershoot()
        {
            var a=Road("a",12,"primary",-20,0,0,0);var b=Road("b",6,"primary",0,0,0.02,0);var c=Road("c",10,"primary",0.02,0,20,0);
            var result=Build(a,b,c);Valid(result);Assert.That(result.Transitions.Count,Is.EqualTo(2));
            Assert.That(result.Mesh(b).Vertices.Min(v=>v.x),Is.GreaterThanOrEqualTo(0));
            Assert.That(result.Mesh(b).Vertices.Max(v=>v.x),Is.LessThanOrEqualTo(0.02001));
        }
        [Test]
        public void NormalizationKeepsJunctionAndRealCorner()
        {
            var a=Road("a",6,"primary",-20,0,-19.99,0.001,0,0,10,10,20,10);
            var b=Road("b",4,"service",0,0,0,-20);
            var result=Build(a,b);Valid(result);Assert.That(result.RemovedPoints,Is.GreaterThan(0));
            Assert.That(result.Junctions.Count,Is.EqualTo(1));
            Assert.That(result.Centerlines.First().Any(v=>v.x==10&&v.z==10),Is.True);
            Assert.That(a.path.Length,Is.EqualTo(5));
        }
        [Test]
        public void ConnectedPathsAndClosedLoopHaveNoInternalCaps()
        {
            var a=Road("a",2,"footway",-20,0,0,0);var b=Road("b",2,"footway",0,0,20,0);
            var result=Build(a,b);Valid(result);Assert.That(result.TerminalCaps,Is.EqualTo(2));
            var loop=Road("loop",2,"footway",0,0,20,0,20,20,0,20,0,0);
            result=Build(loop);Valid(result);Assert.That(result.TerminalCaps,Is.Zero);
            var vertices=result.Mesh(loop).Vertices;
            Assert.That(vertices[0],Is.EqualTo(vertices[vertices.Count-2]));
            Assert.That(vertices[1],Is.EqualTo(vertices[vertices.Count-1]));
        }
        [Test]
        public void DeadEndHasCompactCapsAndNoTaper()
        {
            var road=Road("a",6,"residential",0,0,20,0);var result=Build(road);Valid(result);
            Assert.That(result.TerminalCaps,Is.EqualTo(2));Assert.That(result.Transitions,Is.Empty);
            Assert.That(result.Mesh(road).Vertices.Min(v=>v.x),Is.EqualTo(-0.5f).Within(0.001));
            Assert.That(result.Mesh(road).Vertices.Max(v=>v.x),Is.EqualTo(20.5f).Within(0.001));
        }
        [TestCase("../../output/roads-v027/sevastopol/scene.json")]
        [TestCase("../../output/roads-v027/moscow/scene.json")]
        public void RealScenesRegenerateAndFiltersRemoveJunctions(string path)
        {
            var root=new GameObject("v027 validation");
            try
            {
                var g=root.AddComponent<GeoForgeSceneGenerator>();g.sceneJsonPath=path;g.GenerateScene();
                Valid(g.RoadNetwork);
                Assert.That(g.LastStatistics.roadsFailed,Is.Zero);Assert.That(g.LastStatistics.junctionPatches,Is.GreaterThan(0));
                long vertices=g.LastStatistics.vertices;int count=g.LastStatistics.junctionPatches;
                g.ShowAutomotiveRoads=false;g.GenerateRoads();Assert.That(g.LastStatistics.junctionPatches,Is.Zero);Assert.That(g.LastStatistics.widthTransitions,Is.Zero);
                g.ShowAutomotiveRoads=true;g.GenerateRoads();Assert.That(g.LastStatistics.junctionPatches,Is.EqualTo(count));Assert.That(g.LastStatistics.vertices,Is.EqualTo(vertices));
            }
            finally { UnityEngine.Object.DestroyImmediate(root); }
        }
    }
}
