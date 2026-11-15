using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace GeoForge.Tests
{
    public sealed class GeoForgeRoadSemanticsTests
    {
        [Test]
        public void CategoriesUseSharedDistinctMaterialsAndRespectWidth()
        {
            var root = new GameObject("category test");
            try
            {
                var generator = root.AddComponent<GeoForgeSceneGenerator>();
                generator.sceneJsonPath = "../../output/roads-v026/moscow/scene.json";
                generator.GenerateScene();
                Assert.That(generator.LastStatistics.roadsFailed, Is.Zero);
                var roads = generator.LoadedScene.roads;
                var group = root.transform.Find("GeoForgeGenerated/Roads");
                Material previous = null;
                foreach (var category in new[] {"automotive","pedestrian","cycle","steps","other"})
                {
                    var road = roads.First(r=>r.road_category==category);
                    var renderer = group.Cast<Transform>().Single(t=>t.name==road.id).GetComponent<MeshRenderer>();
                    Assert.That(renderer.sharedMaterial, Is.Not.Null);
                    Assert.That(renderer.sharedMaterial, Is.Not.SameAs(previous));
                    previous = renderer.sharedMaterial;
                    var second = roads.Last(r=>GeoForgeSceneGenerator.RoadStyle(r)==GeoForgeSceneGenerator.RoadStyle(road));
                    Assert.That(group.Cast<Transform>().Single(t=>t.name==second.id).GetComponent<MeshRenderer>().sharedMaterial, Is.SameAs(renderer.sharedMaterial));
                    Assert.That(road.width_source, Is.Not.EqualTo("legacy"));
                }
                Assert.That(roads.Any(r=>r.bridge && r.layer!=0), Is.True);
                Assert.That(roads.Any(r=>r.source_ids.Count>1), Is.True);
            }
            finally { Object.DestroyImmediate(root); }
        }
        [Test]
        public void FiltersRegenerateWithoutLosingInventoryOrLeakingGeometry()
        {
            var root = new GameObject("filters");
            try
            {
                var g=root.AddComponent<GeoForgeSceneGenerator>();
                g.sceneJsonPath="../../output/roads-v026/moscow/scene.json"; g.GenerateScene();
                long vertices=g.LastStatistics.vertices;
                int count=g.LoadedScene.roads.Count, steps=g.LastStatistics.steps;
                Assert.That(steps,Is.GreaterThan(0));
                foreach (var category in new[]{"automotive","pedestrian","cycle","steps","track"})
                {
                    g.ShowAutomotiveRoads=category!="automotive"; g.ShowPedestrianPaths=category!="pedestrian";
                    g.ShowCyclePaths=category!="cycle"; g.ShowSteps=category!="steps"; g.ShowTracks=category!="track";
                    g.GenerateRoads();
                    int hidden=g.LoadedScene.roads.Count(r=>r.road_category==category);
                    Assert.That(g.LastStatistics.roadsHidden,Is.EqualTo(hidden));
                    Assert.That(g.LastStatistics.roads,Is.EqualTo(count-hidden));
                    Assert.That(g.LastStatistics.roadsFailed,Is.Zero);
                    Assert.That(g.LastStatistics.steps,Is.EqualTo(steps));
                }
                g.ShowAutomotiveRoads=g.ShowPedestrianPaths=g.ShowCyclePaths=g.ShowSteps=g.ShowTracks=true;
                g.GenerateRoads(); Assert.That(g.LastStatistics.vertices,Is.EqualTo(vertices));
                Assert.That(g.LastStatistics.roads,Is.EqualTo(count));
                Assert.That(root.transform.Find("GeoForgeGenerated/Roads").childCount,Is.EqualTo(count));
                Assert.That(GeoForgeSceneGenerator.RoadStyle(new GeoForgeRoad{road_category="steps",road_type="steps"}),Is.EqualTo("steps"));
                Assert.That(GeoForgeSceneGenerator.RoadStyle(new GeoForgeRoad{road_type="primary_link"}),Is.Not.EqualTo("primary"));
            }
            finally { Object.DestroyImmediate(root); }
        }
        [TestCase("../../output/roads-v026/sevastopol/scene.json")]
        [TestCase("../../output/roads-v026/moscow/scene.json")]
        public void NewScenesGenerateAndRegenerate(string path)
        {
            var root = new GameObject("v025");
            try
            {
                var generator=root.AddComponent<GeoForgeSceneGenerator>();generator.sceneJsonPath=path;
                for(int i=0;i<2;i++)
                {
                    generator.GenerateScene();
                    var s=generator.LastStatistics;
                    Assert.That(s.buildingsFailed+s.roadsFailed+s.waterFailed+s.greenFailed,Is.Zero);
                    Assert.That(s.roads,Is.EqualTo(generator.LoadedScene.roads.Count));
                    Assert.That(root.transform.childCount,Is.EqualTo(1));
                }
            }
            finally { Object.DestroyImmediate(root); }
        }
    }
}
