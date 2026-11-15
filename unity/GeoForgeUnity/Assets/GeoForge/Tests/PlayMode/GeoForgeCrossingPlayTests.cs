using System.Collections;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace GeoForge.Tests
{
    public sealed class GeoForgeCrossingPlayTests
    {
        [UnityTest]
        public IEnumerator CrossingBeforeRoadInInputStillInheritsRoadCollider()
        {
            var root=new GameObject("crossing authority play");
            var overview=new GameObject("overview");overview.AddComponent<Camera>();overview.tag="MainCamera";
            try {
                var auto=new GeoForgeRoad{id="auto",road_category="automotive",road_type="residential",layer=0,width=6,
                    path=new[]{new[]{2d,10d,0d},new[]{18d,10d,0d}},
                    vertical_profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{2d,10d,6d},new[]{18d,10d,6d}}}};
                var walk=new GeoForgeRoad{id="walk",road_category="pedestrian",road_type="footway",road_subtype="crossing",layer=0,width=2,
                    path=new[]{new[]{10d,2d,0d},new[]{10d,18d,0d}},
                    vertical_profile=new GeoForgeRoadVerticalProfile{points=new[]{new[]{10d,2d,1d},new[]{10d,18d,1d}}}};
                var scene=new GeoForgeScene{
                    bounds=new GeoForgeBounds{min_x=0,min_y=0,max_x=20,max_y=20},
                    metadata=new GeoForgeMetadata{selection_boundary=new GeoForgePolygon{
                        exterior=new[]{new[]{0d,0d,0d},new[]{20d,0d,0d},new[]{20d,20d,0d},new[]{0d,20d,0d},new[]{0d,0d,0d}},holes=new double[0][][]}},
                    terrain=new GeoForgeTerrainData{available=true,resolution_x=3,resolution_y=3,
                        origin=new[]{0d,0d,0d},cell_size=new[]{10d,10d},heights=Enumerable.Repeat(10d,9).ToArray(),
                        valid_mask=Enumerable.Repeat(true,9).ToArray(),min_height=10,max_height=10,
                        sampling="south_to_north_rows_west_to_east_columns"},
                    buildings=new List<GeoForgeBuilding>(),water_areas=new List<GeoForgeArea>(),green_areas=new List<GeoForgeArea>(),
                    roads=new List<GeoForgeRoad>{walk,auto}
                };
                var g=root.AddComponent<GeoForgeSceneGenerator>();g.generateOnStart=false;g.LoadedScene=scene;g.GenerateLoadedScene();
                yield return null;Physics.SyncTransforms();
                Assert.That(g.LastStatistics.roadsFailed,Is.Zero);
                var generated=root.transform.Find("GeoForgeGenerated");
                var ray=new Ray(new Vector3(10,30,10),Vector3.down);
                Assert.That(generated.Find("Roads/auto").GetComponent<MeshCollider>().Raycast(ray,out var ah,100),Is.True);
                Assert.That(generated.Find("Roads/walk").GetComponent<MeshCollider>().Raycast(ray,out var wh,100),Is.True);
                Assert.That(wh.point.y-ah.point.y,Is.EqualTo(0.005).Within(0.002));
                Assert.That(generated.lossyScale,Is.EqualTo(Vector3.one));
                var player=g.Player.GetComponent<CharacterController>();
                Assert.That(player.height,Is.InRange(1.5f,2.1f));Assert.That(player.radius,Is.InRange(0.15f,0.5f));
                Assert.That(scene.terrain.heights.All(h=>h==10),Is.True);
            } finally {Object.Destroy(root);Object.Destroy(overview);}
        }
    }
}
