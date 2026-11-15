using NUnit.Framework;
using UnityEngine;
using System.Collections.Generic;

namespace GeoForge.Tests
{
    public sealed class GeoForgeWalkableTests
    {
        [Test]
        public void ControllerFallsJumpsSprintsAndStopsAtWall()
        {
            var root=new GameObject("physics test");
            try
            {
                GeoForgeCollisionSetup.FlatGround(root.transform,new GeoForgeBounds{min_x=-20,min_y=-20,max_x=20,max_y=20});
                var wall=new GameObject("wall");wall.transform.SetParent(root.transform);wall.transform.position=new Vector3(4,2,0);
                wall.AddComponent<BoxCollider>().size=new Vector3(1,4,20);
                var player=new GameObject("player");player.transform.SetParent(root.transform);player.transform.position=new Vector3(0,2,0);
                var cc=player.AddComponent<CharacterController>();cc.height=1.8f;cc.radius=0.35f;cc.center=new Vector3(0,0.9f,0);cc.skinWidth=0.03f;
                var controller=player.AddComponent<GeoForgePlayerController>();controller.enabled=false;
                Physics.SyncTransforms();
                for(int i=0;i<100;i++)controller.Tick(Vector2.zero,false,false,0.02f);
                Assert.That(player.transform.position.y,Is.InRange(-0.1f,0.15f));
                controller.Tick(Vector2.zero,true,false,0.02f);
                for(int i=0;i<10;i++)controller.Tick(Vector2.zero,false,false,0.02f);
                Assert.That(player.transform.position.y,Is.GreaterThan(0.5f));
                for(int i=0;i<100;i++)controller.Tick(Vector2.zero,false,false,0.02f);
                float x=player.transform.position.x;controller.Tick(Vector2.right,false,false,0.02f);float walk=player.transform.position.x-x;
                x=player.transform.position.x;controller.Tick(Vector2.right,false,true,0.02f);Assert.That(player.transform.position.x-x,Is.GreaterThan(walk));
                for(int i=0;i<100;i++)controller.Tick(Vector2.right,false,true,0.02f);
                Assert.That(player.transform.position.x,Is.LessThan(3.3f));
                GeoForgeWorldBoundary.Create(root.transform,new GeoForgeScene {bounds=new GeoForgeBounds {min_x=-20,min_y=-20,max_x=20,max_y=20}},-10,30);
                Physics.SyncTransforms();
                for(int i=0;i<300;i++)controller.Tick(Vector2.left,false,true,0.02f);
                Assert.That(player.transform.position.x,Is.InRange(-19.3f,-18.9f));
            }
            finally {Object.DestroyImmediate(root);}
        }
        [Test]
        public void RealFlatSceneSpawnsAndClearsColliders()
        {
            var root=new GameObject("walkable");
            try
            {
                var g=root.AddComponent<GeoForgeSceneGenerator>();g.sceneJsonPath="../../output/roads-v027/sevastopol/scene.json";
                g.GenerateScene();Assert.That(g.LastStatistics.playerSpawned,Is.True);Assert.That(g.LastStatistics.colliders,Is.GreaterThan(551));
                var spawn=g.Player.safeSpawn;
                foreach(var b in g.LoadedScene.buildings)Assert.That(GeoForgeSpawnManager.Contains(b.footprint,spawn.x,spawn.z),Is.False);
                g.GenerateScene();Assert.That(root.GetComponentsInChildren<CharacterController>().Length,Is.EqualTo(1));
                g.ClearGeneratedScene();Assert.That(root.GetComponentsInChildren<Collider>(),Is.Empty);
            }
            finally{Object.DestroyImmediate(root);}
        }
    }
}
