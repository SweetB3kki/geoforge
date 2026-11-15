using System.Collections;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace GeoForge.Tests
{
    public sealed class GeoForgePlayModeTests
    {
        [UnityTest]
        public IEnumerator GenerateClearRegenerateAndCameraUpdate()
        {
            var root = new GameObject("PlayMode generator");
            var camera = new GameObject("PlayMode camera");
            try
            {
                camera.AddComponent<Camera>();camera.AddComponent<GeoForgeFreeCamera>();
                var generator = root.AddComponent<GeoForgeSceneGenerator>();
                generator.generateOnStart = false;
                generator.LoadedScene = GeoForgeJsonLoader.Parse(File.ReadAllText(GeoForgeJsonLoader.ResolvePath("../../output/scene.json")));
                generator.GenerateLoadedScene();
                yield return null;
                Assert.That(root.GetComponentsInChildren<MeshFilter>().Length, Is.EqualTo(694));
                generator.GenerateLoadedScene();
                Assert.That(root.transform.childCount, Is.EqualTo(1));
                yield return null;
                Assert.That(root.GetComponentsInChildren<MeshFilter>().Length, Is.EqualTo(694));
                generator.ClearGeneratedScene();
                yield return null;
                Assert.That(root.transform.childCount, Is.Zero);
                Assert.That(camera.GetComponent<GeoForgeFreeCamera>().enabled, Is.True);
            }
            finally { Object.Destroy(root); Object.Destroy(camera); }
            yield return null;
        }
    }
}
