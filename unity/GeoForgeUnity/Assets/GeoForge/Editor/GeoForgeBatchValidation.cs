using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace GeoForge.Editor
{
    public static partial class GeoForgeBatchValidation
    {
        public static void RenderEnvironmentExamples()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var generator=UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();var camera=Camera.main;
            foreach(var city in new[]{"sevastopol","moscow"})
            {
                string prefix="../../output/environment-v04/unity/"+city;
                Render(generator,camera,"../../output/environment-v04/"+city+"/scene.json",prefix);
                if(!generator.LastStatistics.playerSpawned)throw new Exception("No safe player spawn: "+city);
                var playerCamera=generator.Player.view;playerCamera.fieldOfView=generator.Player.fieldOfView;
                Capture(playerCamera,GeoForgeJsonLoader.ResolvePath(prefix+"-walk.png"));
            }
            generator.ClearGeneratedScene();generator.sceneJsonPath="../../output/environment-v04/sevastopol/scene.json";
            camera.transform.position=new Vector3(0,650,-750);camera.transform.LookAt(Vector3.zero);camera.orthographic=false;
            EditorSceneManager.SaveScene(generator.gameObject.scene);
            Debug.Log("GeoForge v0.3-v0.4 environment rendering completed.");
        }
        public static void RenderRoadGeometryExamples()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var generator = UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();
            var camera = Camera.main;
            Render(generator,camera,"../../output/roads-v027/sevastopol/scene.json","../../output/roads-v027/unity/sevastopol");
            Render(generator,camera,"../../output/roads-v027/moscow/scene.json","../../output/roads-v027/unity/moscow");
            RenderGeometryFixtures(generator,camera);
            generator.ClearGeneratedScene();
            generator.sceneJsonPath="../../output/roads-v027/sevastopol/scene.json";
            camera.transform.position=new Vector3(0,650,-750);camera.transform.LookAt(Vector3.zero);camera.orthographic=false;
            EditorSceneManager.SaveScene(generator.gameObject.scene);
            Debug.Log("GeoForge v0.2.7 rendering completed.");
        }
        private static GeoForgeRoad FixtureRoad(string id, double width, params double[] xy)
        {
            return new GeoForgeRoad {id=id,width=width,road_type="primary",road_category="automotive",
                path=Enumerable.Range(0,xy.Length/2).Select(i=>new[]{xy[2*i],xy[2*i+1],0d}).ToArray()};
        }
        private static void RenderGeometryFixtures(GeoForgeSceneGenerator generator, Camera camera)
        {
            var fixtures=new Dictionary<string,List<GeoForgeRoad>> {
                {"transition",new List<GeoForgeRoad>{FixtureRoad("a",12,-30,0,0,0),FixtureRoad("b",6,0,0,30,0)}},
                {"junction-t",new List<GeoForgeRoad>{FixtureRoad("a",6,-30,0,0,0,30,0),FixtureRoad("b",6,0,0,0,30)}},
                {"junction-x",new List<GeoForgeRoad>{FixtureRoad("a",6,-30,0,0,0,30,0),FixtureRoad("b",6,0,-30,0,0,0,30)}},
                {"junction-y",new List<GeoForgeRoad>{FixtureRoad("a",6,0,-30,0,0),FixtureRoad("b",6,0,0,-20,25),FixtureRoad("c",6,0,0,20,25)}}
            };
            string directory=GeoForgeJsonLoader.ResolvePath("../../output/roads-v027/fixtures");Directory.CreateDirectory(directory);
            foreach(var pair in fixtures)
            {
                generator.LoadedScene=new GeoForgeScene {roads=pair.Value,buildings=new List<GeoForgeBuilding>(),water_areas=new List<GeoForgeArea>(),green_areas=new List<GeoForgeArea>()};
                generator.GenerateLoadedScene();
                camera.orthographic=true;camera.orthographicSize=36;camera.transform.position=new Vector3(0,100,0);camera.transform.rotation=Quaternion.Euler(90,0,0);
                Capture(camera,Path.Combine(directory,pair.Key+"-after.png"));
                var group=generator.transform.Find("GeoForgeGenerated/Roads");
                foreach(var road in pair.Value)
                {
                    var filter=group.Cast<Transform>().Single(t=>t.name==road.id).GetComponent<MeshFilter>();
                    var old=filter.sharedMesh;filter.sharedMesh=GeoForgeRoadGenerator.Build(road).ToMesh(road.id);UnityEngine.Object.DestroyImmediate(old);
                }
                Capture(camera,Path.Combine(directory,pair.Key+"-before.png"));
            }
        }
        public static void RenderFinalRoadExamples()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var generator = UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();
            var camera = Camera.main;
            Render(generator,camera,"../../output/roads-v026/sevastopol/scene.json","../../output/roads-v026/unity/sevastopol");
            Render(generator,camera,"../../output/roads-v026/moscow/scene.json","../../output/roads-v026/unity/moscow");
            generator.ClearGeneratedScene();
            generator.sceneJsonPath="../../output/roads-v026/sevastopol/scene.json";
            camera.transform.position=new Vector3(0,650,-750);camera.transform.LookAt(Vector3.zero);camera.orthographic=false;
            EditorSceneManager.SaveScene(generator.gameObject.scene);
            Debug.Log("GeoForge v0.2.6 rendering completed.");
        }
        public static void RenderRoadExamples()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var generator = UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();
            var camera = Camera.main;
            Render(generator,camera,"../../output/roads-v025/sevastopol/scene.json","../../output/roads-v025/unity/sevastopol");
            Render(generator,camera,"../../output/roads-v025/moscow/scene.json","../../output/roads-v025/unity/moscow");
            generator.ClearGeneratedScene();
            generator.sceneJsonPath="../../output/roads-v025/sevastopol/scene.json";
            camera.transform.position=new Vector3(0,650,-750);camera.transform.LookAt(Vector3.zero);camera.orthographic=false;
            EditorSceneManager.SaveScene(generator.gameObject.scene);
            Debug.Log("GeoForge v0.2.5 rendering completed.");
        }
        // Run with graphics enabled (omit -nographics) for actual Unity camera PNGs.
        public static void RenderExamples()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var generator = UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();
            var camera = Camera.main;
            Render(generator,camera,"../../output/scene.json","../../output/unity/sevastopol");
            Render(generator,camera,"../../output/water-example/scene.json","../../output/unity/moscow");
            generator.ClearGeneratedScene();
            generator.sceneJsonPath="../../output/scene.json";
            camera.transform.position=new Vector3(0,650,-750);camera.transform.LookAt(Vector3.zero);
            camera.orthographic=false;
            EditorSceneManager.SaveScene(generator.gameObject.scene);
            Debug.Log("GeoForge render validation completed.");
        }
        private static void Render(GeoForgeSceneGenerator generator,Camera camera,string input,string output)
        {
            generator.sceneJsonPath=input;generator.GenerateScene();
            var s=generator.LastStatistics;
            if(s==null || s.buildingsFailed+s.roadsFailed+s.waterFailed+s.greenFailed!=0)
                throw new Exception("Example has failed objects; see log.");
            string prefix=GeoForgeJsonLoader.ResolvePath(output);Directory.CreateDirectory(Path.GetDirectoryName(prefix));
            File.WriteAllText(prefix+"-statistics.json",JsonUtility.ToJson(s,true));
            if (generator.RoadNetwork != null)
            {
                var network = generator.RoadNetwork;
                var audit = new {
                    junctions = network.Junctions.Select(j => new {position=new[]{j.Position.x,j.Position.y,j.Position.z},
                        roads=j.ConnectedRoadIds,widths=j.ConnectedWidths,layer=j.Layer,bridge=j.Bridge,tunnel=j.Tunnel,
                        polygon=j.Polygon.Select(p=>new[]{p.x,p.y,p.z})}),
                    transitions = network.Transitions.Select(t => new {position=new[]{t.Position.x,t.Position.y,t.Position.z},
                        start=new[]{t.Start.x,t.Start.y,t.Start.z},end=new[]{t.End.x,t.End.y,t.End.z},
                        firstWidth=t.FirstWidth,sharedWidth=t.SharedWidth,secondWidth=t.SecondWidth})
                };
                File.WriteAllText(prefix+"-geometry.json",Newtonsoft.Json.JsonConvert.SerializeObject(audit,Newtonsoft.Json.Formatting.Indented));
            }
            var bounds=generator.LoadedScene.bounds;
            float centerX=(float)((bounds.min_x+bounds.max_x)/2),centerZ=(float)((bounds.min_y+bounds.max_y)/2);
            float extent=(float)Math.Max(bounds.max_x-bounds.min_x,bounds.max_y-bounds.min_y);
            camera.orthographic=true;camera.orthographicSize=extent*0.55f;
            camera.transform.position=new Vector3(centerX,extent*2,centerZ);camera.transform.rotation=Quaternion.Euler(90,0,0);
            Capture(camera,prefix+"-top.png");
            camera.orthographic=false;camera.transform.position=new Vector3(centerX,extent*0.75f,centerZ-extent*0.9f);
            camera.transform.LookAt(new Vector3(centerX,0,centerZ));Capture(camera,prefix+"-3d.png");
        }
        private static void Capture(Camera camera,string path)
        {
            var target=new RenderTexture(1400,1400,24);target.Create();
            var image=new Texture2D(1400,1400,TextureFormat.RGB24,false);
            var previous=RenderTexture.active;
            try
            {
                camera.targetTexture=target;camera.Render();RenderTexture.active=target;
                image.ReadPixels(new Rect(0,0,1400,1400),0,0);image.Apply();File.WriteAllBytes(path,image.EncodeToPNG());
            }
            finally
            { camera.targetTexture=null;RenderTexture.active=previous;target.Release();UnityEngine.Object.DestroyImmediate(target);UnityEngine.Object.DestroyImmediate(image); }
        }
    }
}
