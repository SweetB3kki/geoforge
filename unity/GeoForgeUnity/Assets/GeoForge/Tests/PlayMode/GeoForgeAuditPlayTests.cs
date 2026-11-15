using System.Collections;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace GeoForge.Tests
{
    public sealed class GeoForgeAuditPlayTests
    {
        [System.Serializable] private sealed class Measurement
        {
            public string city, mode="PlayMode explicit Camera.Render, 1280x720, 120 frames";
            public float fps, elapsedSeconds;
            public int frames=120;
            public Vector3 spawn;
            public GeoForgeSceneGenerator.Statistics generation;
        }
        [UnityTest]
        public IEnumerator AuditBeforeAfterPlayerAndGraphicsBenchmark()
        {
            foreach(var city in new[]{"sevastopol","moscow"})
            foreach(var phase in new[]{"before","after"})
            {
                var root=new GameObject("environment play");var overview=new GameObject("overview");
                overview.AddComponent<Camera>();overview.tag="MainCamera";
                var target=new RenderTexture(1280,720,24);target.Create();
                try
                {
                    var sun=new GameObject("benchmark sun");sun.transform.SetParent(root.transform);
                    var light=sun.AddComponent<Light>();light.type=LightType.Directional;light.intensity=1.1f;
                    light.shadows=LightShadows.Soft;sun.transform.rotation=Quaternion.Euler(50,-30,0);
                    var g=root.AddComponent<GeoForgeSceneGenerator>();g.generateOnStart=false;g.enableBuildingFoundations=phase=="after";g.terrainConform.adaptive=phase=="after";
                    g.sceneJsonPath="../../output/audit-v041/"+city+"/scene.json";g.GenerateScene();
                    Assert.That(g.LastStatistics.roadsFailed+g.LastStatistics.buildingsFailed+g.LastStatistics.waterFailed+g.LastStatistics.greenFailed,Is.Zero);
                    Assert.That(g.Player,Is.Not.Null);
                    yield return new WaitForSeconds(0.6f);
                    var p=g.Player.transform.position;
                    Assert.That(p.y-g.TerrainSampler.SampleHeight(p.x,p.z),Is.InRange(-0.15f,0.3f));
                    Assert.That(g.Player.view.enabled,Is.True);
                    g.Player.view.targetTexture=target;
                    for(int i=0;i<10;i++){g.Player.view.Render();yield return null;}
                    var watch=System.Diagnostics.Stopwatch.StartNew();
                    for(int i=0;i<120;i++){g.Player.view.Render();yield return null;}
                    watch.Stop();
                    string directory=GeoForgeJsonLoader.ResolvePath("../../output/test-runs/audit-v041/"+city);Directory.CreateDirectory(directory);
                    File.WriteAllText(Path.Combine(directory,"play-"+phase+".json"),JsonUtility.ToJson(new Measurement {
                        city=city,fps=120f/(float)watch.Elapsed.TotalSeconds,elapsedSeconds=(float)watch.Elapsed.TotalSeconds,spawn=p,generation=g.LastStatistics},true));
                    var previous=RenderTexture.active;RenderTexture.active=target;
                    var image=new Texture2D(1280,720,TextureFormat.RGB24,false);
                    image.ReadPixels(new Rect(0,0,1280,720),0,0);image.Apply();
                    File.WriteAllBytes(Path.Combine(directory,"play-"+phase+".png"),image.EncodeToPNG());
                    Object.Destroy(image);RenderTexture.active=previous;g.Player.view.targetTexture=null;
                    if(city=="sevastopol")
                    {
                        g.Player.enabled=false;var start=g.Player.transform.position;
                        for(int k=0;k<20;k++)g.Player.Tick(Vector2.up,false,false,0.02f);
                        Assert.That(Vector3.Distance(start,g.Player.transform.position),Is.GreaterThan(0.2f));
                    }
                    g.GenerateScene();yield return null;
                    Assert.That(root.GetComponentsInChildren<CharacterController>().Length,Is.EqualTo(1));
                    g.ClearGeneratedScene();yield return null;
                    Assert.That(root.GetComponentsInChildren<Collider>(),Is.Empty);
                }
                finally{Object.Destroy(root);Object.Destroy(overview);target.Release();Object.Destroy(target);}
            }
        }
    }
}
