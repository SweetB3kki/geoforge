using System.Collections;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace GeoForge.Tests
{
    public sealed class GeoForgeMultisourcePlayTests
    {
        [UnityTest]
        public IEnumerator RealPartsPlayerRegenerationAndCleanup()
        {
            foreach(var city in new[]{"sevastopol","moscow"})
            {
                var root=new GameObject("multisource play");var overview=new GameObject("overview");
                overview.AddComponent<Camera>();overview.tag="MainCamera";
                try
                {
                    var g=root.AddComponent<GeoForgeSceneGenerator>();g.generateOnStart=false;
                    g.sceneJsonPath="../../output/multisource-v05/"+city+"/scene.json";g.GenerateScene();
                    Assert.That(g.LastStatistics.buildingsFailed+g.LastStatistics.roadsFailed+g.LastStatistics.waterFailed,Is.Zero);
                    Assert.That(g.Player,Is.Not.Null);
                    if(city=="moscow")Assert.That(g.LastStatistics.buildingParts,Is.GreaterThan(0));
                    yield return new WaitForSeconds(0.6f);
                    var p=g.Player.transform.position;
                    Assert.That(p.y-g.TerrainSampler.SampleHeight(p.x,p.z),Is.InRange(-0.15f,0.3f));
                    int meshes=root.GetComponentsInChildren<MeshFilter>().Length;
                    g.GenerateScene();yield return null;
                    Assert.That(root.GetComponentsInChildren<MeshFilter>().Length,Is.EqualTo(meshes));
                    Assert.That(root.GetComponentsInChildren<CharacterController>().Length,Is.EqualTo(1));
                    Assert.That(g.LoadedScene.buildings.SelectMany(b=>b.parts??new System.Collections.Generic.List<GeoForgeBuilding>()).All(b=>b.parent_id!=null),Is.True);
                    g.ClearGeneratedScene();yield return null;
                    Assert.That(root.GetComponentsInChildren<Collider>(),Is.Empty);
                }
                finally {Object.Destroy(root);Object.Destroy(overview);}
            }
        }
    }
}
