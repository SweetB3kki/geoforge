using System;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using UnityEngine;
using UnityEditor.SceneManagement;

namespace GeoForge.Editor
{
    public static partial class GeoForgeBatchValidation
    {
        public static void RenderMultisourceExamples()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var g=UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();
            var camera=Camera.main;
            foreach(var city in new[]{"sevastopol","moscow"})
            {
                string folder="../../output/multisource-v05/"+city;
                Render(g,camera,"../../output/audit-v041/"+city+"/scene.json",folder+"/unity-before");
                WriteQuality(g,folder+"/unity-before-quality.json");
                Render(g,camera,folder+"/scene.json",folder+"/unity");
                WriteQuality(g,folder+"/unity-quality.json");
                if(!g.LastStatistics.playerSpawned)throw new Exception("No safe player spawn: "+city);
                Capture(g.Player.view,GeoForgeJsonLoader.ResolvePath(folder+"/unity-street.png"));
                var detailed=g.LoadedScene.buildings.Where(b=>b.parts!=null&&b.parts.Count>0).OrderByDescending(b=>b.parts.Count).ThenBy(b=>b.id).FirstOrDefault();
                if(detailed!=null)
                {
                    var ring=detailed.footprint.exterior;
                    float extent=(float)Math.Max(ring.Max(p=>p[0])-ring.Min(p=>p[0]),ring.Max(p=>p[1])-ring.Min(p=>p[1]));
                    var focus=new Vector3((float)ring.Average(p=>p[0]),GeoForgeBuildingVolumes.Ground(detailed,g.TerrainSampler),(float)ring.Average(p=>p[1]));
                    Closeup(camera,focus,Math.Max(50,extent),folder+"/unity-building-parts.png");
                    // Phase D stored part candidates but did not render them. Reproduce that
                    // renderer input for a matched-camera comparison, without altering the snapshot.
                    string snapshot="../../output/multisource-v05/phase-d/"+city+"/scene.json";
                    if(File.Exists(GeoForgeJsonLoader.ResolvePath(snapshot)))
                    {
                        var old=GeoForgeJsonLoader.Load(snapshot);
                        foreach(var b in old.buildings)b.parts=null;
                        g.LoadedScene=old;g.GenerateLoadedScene();
                        Closeup(camera,focus,Math.Max(50,extent),folder+"/unity-building-parts-before.png");
                        g.GenerateScene();
                    }

                    File.WriteAllText(GeoForgeJsonLoader.ResolvePath(folder+"/parts-viewpoint.json"),JsonConvert.SerializeObject(new {id=detailed.id,parts=detailed.parts.Count,selection="largest part count, deterministic ID tie break"},Formatting.Indented));
                }

                var area=g.LoadedScene.water_areas.OrderByDescending(a=>a.water_type=="ocean").ThenByDescending(a=>RingArea(a.polygon.exterior)).First();
                var center=new Vector3((float)area.polygon.exterior.Average(p=>p[0]),GeoForgeWaterLevel.Resolve(area,g.TerrainSampler),(float)area.polygon.exterior.Average(p=>p[1]));
                Closeup(camera,center,area.water_type=="ocean"?120:220,folder+"/unity-water-coast.png");
                File.WriteAllText(GeoForgeJsonLoader.ResolvePath(folder+"/water-viewpoint.json"),JsonConvert.SerializeObject(new {id=area.id,center=new[]{center.x,center.y,center.z},level=area.water_level_m,method=area.water_height_method,selection="ocean first, otherwise largest polygon"},Formatting.Indented));
            }
            g.ClearGeneratedScene();g.sceneJsonPath="../../output/multisource-v05/sevastopol/scene.json";
            camera.transform.position=new Vector3(0,650,-750);camera.transform.LookAt(Vector3.zero);camera.orthographic=false;
            EditorSceneManager.SaveScene(g.gameObject.scene);
            Debug.Log("GeoForge v0.5 multisource rendering completed.");
        }
    }
}
