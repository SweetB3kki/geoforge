using System.Collections;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace GeoForge.Tests
{
    public sealed class GeoForgeRoadProfilePlayTests
    {
        [UnityTest]
        public IEnumerator PlayerStandsOnConditionedRoadBelowRawDsmAndRegenerates()
        {
            var root=new GameObject("profile play");var overview=new GameObject("overview");
            overview.AddComponent<Camera>();overview.tag="MainCamera";
            try
            {
                var scene=new GeoForgeScene{
                    bounds=new GeoForgeBounds{min_x=0,min_y=0,max_x=20,max_y=20},
                    metadata=new GeoForgeMetadata{selection_boundary=new GeoForgePolygon{
                        exterior=new[]{new[]{0d,0d,0d},new[]{20d,0d,0d},new[]{20d,20d,0d},new[]{0d,20d,0d},new[]{0d,0d,0d}},holes=new double[0][][]}},
                    terrain=new GeoForgeTerrainData{available=true,resolution_x=3,resolution_y=3,
                        origin=new[]{0d,0d,0d},cell_size=new[]{10d,10d},heights=Enumerable.Repeat(10d,9).ToArray(),
                        valid_mask=Enumerable.Repeat(true,9).ToArray(),min_height=10,max_height=10,
                        sampling="south_to_north_rows_west_to_east_columns"},
                    buildings=new List<GeoForgeBuilding>(),water_areas=new List<GeoForgeArea>(),green_areas=new List<GeoForgeArea>(),
                    roads=new List<GeoForgeRoad>{new GeoForgeRoad{id="road",road_type="residential",width=6,
                        path=new[]{new[]{2d,10d,0d},new[]{18d,10d,0d}},vertical_profile=new GeoForgeRoadVerticalProfile{
                            points=new[]{new[]{2d,10d,6d},new[]{18d,10d,6d}}}}}
                };
                var g=root.AddComponent<GeoForgeSceneGenerator>();g.generateOnStart=false;g.LoadedScene=scene;g.GenerateLoadedScene();
                yield return null;
                Assert.That(g.LastStatistics.roadsFailed,Is.Zero);Assert.That(g.Player,Is.Not.Null);
                g.Player.enabled=false;var controller=g.Player.GetComponent<CharacterController>();
                controller.enabled=false;g.Player.transform.position=new Vector3(10,6.5f,10);controller.enabled=true;
                Physics.SyncTransforms();
                for(int i=0;i<90;i++)g.Player.Tick(Vector2.zero,false,false,1f/60);
                Assert.That(g.Player.transform.position.y,Is.InRange(5.95f,6.15f));
                Assert.That(g.RoadBankAudit,Is.Not.Null);
                Assert.That(g.RoadBankAudit.MissingRoadSurfaceMeters,Is.LessThan(0.001));
                Assert.That(root.transform.Find("GeoForgeGenerated/Terrain/RoadBanks"),Is.Not.Null);
                for(int i=0;i<60;i++)controller.Move(new Vector3(0,-0.01f,0.1f));
                Assert.That(g.Player.transform.position.z,Is.InRange(11.5f,13f),"The cut wall must stop the capsule entering the terrain.");
                Assert.That(g.Player.transform.position.y,Is.InRange(5.95f,6.15f));
                Assert.That(scene.terrain.heights.All(h=>h==10));
                int meshes=root.GetComponentsInChildren<MeshFilter>().Length;
                g.GenerateLoadedScene();yield return null;
                Assert.That(root.GetComponentsInChildren<MeshFilter>().Length,Is.EqualTo(meshes));
                Assert.That(root.GetComponentsInChildren<CharacterController>().Length,Is.EqualTo(1));
                g.ClearGeneratedScene();yield return null;Assert.That(root.GetComponentsInChildren<Collider>(),Is.Empty);
                Assert.That(g.RoadBankAudit,Is.Null);
            }
            finally{Object.Destroy(root);Object.Destroy(overview);}
        }
    }
}
