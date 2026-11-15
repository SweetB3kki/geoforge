using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeTerrainTests
    {
        public static GeoForgePolygon Rectangle(double x,double z,double width,double depth)
            => new GeoForgePolygon{exterior=new[]{new[]{x,z,0},new[]{x+width,z,0},new[]{x+width,z+depth,0},new[]{x,z+depth,0},new[]{x,z,0}},holes=Array.Empty<double[][]>()};
        public static GeoForgeScene Slope()
        {
            return new GeoForgeScene {bounds=new GeoForgeBounds{min_x=0,min_y=0,max_x=10,max_y=10},
                metadata=new GeoForgeMetadata{selection_boundary=Rectangle(0,0,10,10)},
                terrain=new GeoForgeTerrainData{available=true,resolution_x=3,resolution_y=3,origin=new[]{0d,0,0},cell_size=new[]{5d,5},
                    heights=new[]{0d,0.5,1,1,1.5,2,2,2.5,3},valid_mask=Enumerable.Repeat(true,9).ToArray(),min_height=0,max_height=3,
                    sampling="south_to_north_rows_west_to_east_columns"},
                buildings=new List<GeoForgeBuilding>(),roads=new List<GeoForgeRoad>(),water_areas=new List<GeoForgeArea>(),green_areas=new List<GeoForgeArea>()};
        }
        [Test]
        public void TerrainOrientationBoundsAndColliderMatchSampler()
        {
            var scene=Slope();var sampler=new GeoForgeTerrainSampler(scene);var data=GeoForgeTerrainGenerator.Build(scene,sampler);
            Assert.That(sampler.SampleHeight(2,3),Is.EqualTo(0.8f).Within(0.0001));
            Assert.That(sampler.SampleHeight(10,0),Is.EqualTo(1));Assert.That(sampler.SampleHeight(0,10),Is.EqualTo(2));
            var root=new GameObject("terrain");var mesh=data.ToMesh("test");
            try
            {
                root.AddComponent<MeshCollider>().sharedMesh=mesh;Physics.SyncTransforms();
                Assert.That(Physics.Raycast(new Vector3(2,10,3),Vector3.down,out var hit,20),Is.True);
                Assert.That(hit.point.y,Is.EqualTo(sampler.SampleHeight(2,3)).Within(0.001));
                Assert.That(mesh.bounds.min,Is.EqualTo(Vector3.zero));Assert.That(mesh.bounds.max,Is.EqualTo(new Vector3(10,3,10)));
            }
            finally{UnityEngine.Object.DestroyImmediate(root);UnityEngine.Object.DestroyImmediate(mesh);}
        }
        [Test]
        public void DrapingAddsTerrainToEveryFinalRoadVertexWithoutChangingSource()
        {
            var sampler=new GeoForgeTerrainSampler(Slope());
            var road=new GeoForgeRoad{id="road",road_type="primary",road_category="automotive",width=2,path=new[]{new[]{1d,5,0},new[]{9d,5,0}}};
            var flat=GeoForgeRoadGenerator.BuildNetwork(new[]{road},new GeoForgeRoadGeometrySettings()).Mesh(road);
            var draped=sampler.Drape(flat);
            Assert.That(flat.Vertices.All(v=>Math.Abs(v.y-0.03f)<0.0001),Is.True);
            foreach(var v in draped.Vertices)Assert.That(v.y-sampler.SampleHeight(v.x,v.z),Is.EqualTo(0.03f).Within(0.0001));
        }
        [Test]
        public void BuildingsStayRigidWaterStaysHorizontalAndGreenFollowsTerrain()
        {
            var scene=Slope();scene.buildings.Add(new GeoForgeBuilding{id="house",height=3,footprint=Rectangle(1,1,2,2)});
            scene.water_areas.Add(new GeoForgeArea{id="water",area_type="water",polygon=Rectangle(0,0,1,1)});
            scene.green_areas.Add(new GeoForgeArea{id="green",area_type="green",polygon=Rectangle(5,5,3,3)});
            var root=new GameObject("placement");
            try
            {
                var g=root.AddComponent<GeoForgeSceneGenerator>();g.LoadedScene=scene;g.GenerateLoadedScene();
                var building=root.transform.Find("GeoForgeGenerated/Buildings/house").GetComponent<MeshFilter>().sharedMesh;
                Assert.That(building.bounds.size.y,Is.EqualTo(3).Within(0.001));Assert.That(building.bounds.min.y,Is.GreaterThan(0));
                Assert.That(root.transform.Find("GeoForgeGenerated/Buildings/house").GetComponent<MeshCollider>(),Is.Not.Null);
                var water=root.transform.Find("GeoForgeGenerated/Water/water").GetComponent<MeshFilter>().sharedMesh;
                Assert.That(water.bounds.size.y,Is.Zero);
                var green=root.transform.Find("GeoForgeGenerated/Green/green").GetComponent<MeshFilter>().sharedMesh;
                foreach(var v in green.vertices)Assert.That(v.y-g.TerrainSampler.SampleHeight(v.x,v.z),Is.EqualTo(0.015f).Within(0.001));
                Assert.That(g.LastStatistics.playerSpawned,Is.True);
                g.GenerateLoadedScene();Assert.That(root.GetComponentsInChildren<CharacterController>().Length,Is.EqualTo(1));
                g.ClearGeneratedScene();Assert.That(root.GetComponentsInChildren<MeshFilter>(),Is.Empty);
            }
            finally{UnityEngine.Object.DestroyImmediate(root);}
        }
        [Test]
        public void NonplanarCellsCannotCutThroughRoadOrGreenOverlay()
        {
            var scene=Slope();scene.terrain.heights=new[]{0d,0,0,0,4,0,0,0,0};
            var sampler=new GeoForgeTerrainSampler(scene);
            var source=new GeoForgeMeshData();source.Vertices.AddRange(new[]{new Vector3(0,0.03f,0),new Vector3(10,0.03f,0),new Vector3(10,0.03f,10),new Vector3(0,0.03f,10)});
            source.AddUpTriangle(0,1,2);source.AddUpTriangle(0,2,3);
            var draped=sampler.Drape(source);
            for(int i=0;i<draped.Triangles.Count;i+=3)
            {
                var center=(draped.Vertices[draped.Triangles[i]]+draped.Vertices[draped.Triangles[i+1]]+draped.Vertices[draped.Triangles[i+2]])/3;
                Assert.That(center.y-sampler.SampleHeight(center.x,center.z),Is.EqualTo(0.03f).Within(0.0001));
            }
        }
        [Test]
        public void VisibleTerrainExcludesWaterButKeepsOriginalDemColliderSurface()
        {
            var scene=Slope();var water=Rectangle(2,2,6,6);
            scene.water_areas.Add(new GeoForgeArea{area_type="water",polygon=water});
            var sampler=new GeoForgeTerrainSampler(scene);var mesh=GeoForgeTerrainGenerator.BuildVisible(scene,sampler);
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var center=(mesh.Vertices[mesh.Triangles[i]]+mesh.Vertices[mesh.Triangles[i+1]]+mesh.Vertices[mesh.Triangles[i+2]])/3;
                Assert.That(GeoForgeSpawnManager.Contains(water,center.x,center.z),Is.False);
            }
            Assert.That(sampler.SampleHeight(5,5),Is.EqualTo(1.5f));
            Assert.That(GeoForgeTerrainGenerator.Build(scene,sampler).Triangles.Count,Is.EqualTo(24));
        }
        [Test]
        public void BadGridRejectedAndLegacyFlatSamplerWorks()
        {
            var scene=Slope();scene.terrain.cell_size[0]=6;Assert.Throws<ArgumentException>(()=>new GeoForgeTerrainSampler(scene));
            scene.terrain=null;Assert.That(new GeoForgeTerrainSampler(scene).SampleHeight(10,20),Is.Zero);
        }
    }
}
