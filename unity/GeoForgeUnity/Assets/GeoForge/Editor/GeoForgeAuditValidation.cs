using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Newtonsoft.Json;
using UnityEngine;
using UnityEditor.SceneManagement;

namespace GeoForge.Editor
{
    public static partial class GeoForgeBatchValidation
    {
        public static void RenderAuditExamples()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var g=UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();var camera=Camera.main;
            foreach(var city in new[]{"sevastopol","moscow"})
            {
                string folder="../../output/audit-v041/"+city;
                string prefix=folder+"/unity";
                // Same inputs and light, before/after changing only foundations/adaptation.
                g.enableBuildingFoundations=false;g.terrainConform.adaptive=false;
                Render(g,camera,folder+"/scene.json",prefix+"-before");
                WriteQuality(g,prefix+"-before-quality.json");
                var worst=g.BuildingAudit.OrderByDescending(q=>q.maximumGap).First();
                Closeup(camera,worst.center,45,prefix+"-building-before.png");
                g.enableBuildingFoundations=true;g.terrainConform.adaptive=true;
                Render(g,camera,folder+"/scene.json",prefix);
                WriteQuality(g,prefix+"-quality.json");
                Capture(g.Player.view,GeoForgeJsonLoader.ResolvePath(prefix+"-street.png"));
                Closeup(camera,worst.center,45,prefix+"-building-slope.png");
                var road=g.LoadedScene.roads.OrderByDescending(r=>r.path.Max(p=>g.TerrainSampler.SampleHeight((float)p[0],(float)p[1]))-r.path.Min(p=>g.TerrainSampler.SampleHeight((float)p[0],(float)p[1]))).First();
                var rp=road.path[road.path.Length/2];var rc=new Vector3((float)rp[0],g.TerrainSampler.SampleHeight((float)rp[0],(float)rp[1]),(float)rp[1]);
                Closeup(camera,rc,45,prefix+"-road-slope.png");
                var junction=g.RoadNetwork.Junctions.OrderByDescending(j=>j.ConnectedRoadIds.Count()).First();
                var jp=junction.Position;jp.y+=g.TerrainSampler.SampleHeight(jp.x,jp.z);Closeup(camera,jp,70,prefix+"-junction.png");
                Vector3 waterCenter=Vector3.zero;string waterId="no water polygon";
                if(g.LoadedScene.water_areas.Count>0)
                {var area=g.LoadedScene.water_areas.OrderByDescending(a=>a.polygon.exterior.Length).First();waterCenter=new Vector3((float)area.polygon.exterior.Average(p=>p[0]),g.TerrainSampler.PolygonHeight(area.polygon,true),(float)area.polygon.exterior.Average(p=>p[1]));waterId=area.id;}
                else
                {
                    var raw=Newtonsoft.Json.Linq.JObject.Parse(File.ReadAllText(GeoForgeJsonLoader.ResolvePath(folder+"/scene.json")));
                    var coast=raw["processing_audit"]?["records"]?.FirstOrDefault(r=>(string)r["source_tags"]?["natural"]=="coastline");
                    var coords=coast?["raw_geometry_local"]?["coordinates"];
                    if(coords!=null&&coords.Any())
                    {
                        var inside=coords.Where(p=>GeoForgeSpawnManager.Contains(g.LoadedScene.metadata.selection_boundary,(float)p[0],(float)p[1])).ToArray();
                        if(inside.Length>0)waterCenter=new Vector3(inside.Average(p=>(float)p[0]),0,inside.Average(p=>(float)p[1]));
                        waterCenter.y=g.TerrainSampler.SampleHeight(waterCenter.x,waterCenter.z);waterId=(string)coast["source_osm_id"];
                    }
                }
                if(g.LoadedScene.water_areas.Count>0)Closeup(camera,waterCenter,200,prefix+"-water-coast.png");
                else
                {camera.orthographic=false;camera.transform.position=new Vector3(waterCenter.x*0.55f,waterCenter.y+110,waterCenter.z*0.55f);camera.transform.LookAt(waterCenter);Capture(camera,GeoForgeJsonLoader.ResolvePath(prefix+"-water-coast.png"));}
                File.WriteAllText(GeoForgeJsonLoader.ResolvePath(folder+"/viewpoints.json"),JsonConvert.SerializeObject(new {building=worst.id,road=road.id,junction=junction.ConnectedRoadIds,water=waterId,selection="maximum building gap, largest road elevation range, most connected junction; not aesthetic selection"},Formatting.Indented));
            }
            g.ClearGeneratedScene();g.sceneJsonPath="../../output/audit-v041/sevastopol/scene.json";
            camera.transform.position=new Vector3(0,650,-750);camera.transform.LookAt(Vector3.zero);camera.orthographic=false;
            EditorSceneManager.SaveScene(g.gameObject.scene);
        }
        private static void Closeup(Camera camera,Vector3 center,float distance,string path)
        {camera.orthographic=false;camera.transform.position=center+new Vector3(distance*0.6f,distance*0.6f,-distance);camera.transform.LookAt(center);Capture(camera,GeoForgeJsonLoader.ResolvePath(path));}
        public static void WriteQuality(GeoForgeSceneGenerator g,string path)
        {
            var root=g.transform.Find("GeoForgeGenerated");
            var water=new List<object>();
            var terrain=root.Find("Terrain")?.GetComponent<MeshFilter>()?.sharedMesh;
            var tv=terrain!=null?terrain.vertices:Array.Empty<Vector3>();var ti=terrain!=null?terrain.triangles:Array.Empty<int>();
            foreach(var area in g.LoadedScene.water_areas)
            {
                var f=root.Find("Water").Cast<Transform>().Single(t=>t.name==area.id).GetComponent<MeshFilter>();var v=f.sharedMesh.vertices;
                int protrusions=0,rawProtrusions=0;float maxProtrusionBoundaryDistance=0;
                for(int i=0;i<ti.Length;i+=3){var p=(tv[ti[i]]+tv[ti[i+1]]+tv[ti[i+2]])/3;if(GeoForgeSpawnManager.Contains(area.polygon,p.x,p.z)&&p.y>v[0].y+0.01f){rawProtrusions++;float d=BoundaryDistance(area.polygon,p);maxProtrusionBoundaryDistance=Mathf.Max(maxProtrusionBoundaryDistance,d);if(d>0.02f)protrusions++;}}
                int outside=0,rawOutside=0;float maxOutsideDistance=0;double meshArea=0;var tris=f.sharedMesh.triangles;
                for(int i=0;i<tris.Length;i+=3){var a=v[tris[i]];var b=v[tris[i+1]];var c=v[tris[i+2]];var p=(a+b+c)/3;if(!GeoForgeSpawnManager.Contains(area.polygon,p.x,p.z)){rawOutside++;float d=BoundaryDistance(area.polygon,p);maxOutsideDistance=Mathf.Max(maxOutsideDistance,d);if(d>0.02f)outside++;}meshArea+=Math.Abs(Vector3.Cross(b-a,c-a).y)*0.5;}
                double polygonArea=RingArea(area.polygon.exterior)-(area.polygon.holes??Array.Empty<double[][]>()).Sum(h=>RingArea(h));
                water.Add(new {id=area.id,horizontalError=v.Max(p=>p.y)-v.Min(p=>p.y),terrainProtrusionSamples=protrusions,outsidePolygonTriangles=outside,rawProtrusions,rawOutside,maxProtrusionBoundaryDistance,maxOutsideDistance,boundaryToleranceMeters=0.02f,meshArea,polygonArea,areaErrorSquareMeters=Math.Abs(meshArea-polygonArea),terrainElevationMismatch=v.Max(p=>Mathf.Abs(p.y-g.TerrainSampler.SampleHeight(p.x,p.z)))});
            }
            var trace=root.GetComponentsInChildren<MeshFilter>().Select(f=>new {scene_object_id=f.gameObject.name=="Foundation"?f.transform.parent.name:f.gameObject.name,gameObject=f.gameObject.name,vertices=f.sharedMesh.vertexCount,triangles=f.sharedMesh.triangles.Length/3,min_y=f.sharedMesh.vertices.Min(v=>v.y),max_y=f.sharedMesh.vertices.Max(v=>v.y)}).ToArray();
            string sceneHash;
            using(var hash=System.Security.Cryptography.SHA256.Create())sceneHash=BitConverter.ToString(hash.ComputeHash(File.ReadAllBytes(GeoForgeJsonLoader.ResolvePath(g.sceneJsonPath)))).Replace("-","").ToLowerInvariant();
            var report=new {stage_of_origin="UNITY_RENDER",scene_sha256=sceneHash,buildings=g.BuildingAudit.ToArray(),surfaces=g.SurfaceAudit.ToArray(),water,performance=g.LastStatistics,trace};
            File.WriteAllText(GeoForgeJsonLoader.ResolvePath(path),JsonConvert.SerializeObject(report,Formatting.Indented,new JsonSerializerSettings {ReferenceLoopHandling=ReferenceLoopHandling.Ignore}));
        }
        private static double RingArea(double[][] ring)
        {double value=0;for(int i=1;i<ring.Length;i++)value+=ring[i-1][0]*ring[i][1]-ring[i][0]*ring[i-1][1];return Math.Abs(value)*0.5;}
        private static float BoundaryDistance(GeoForgePolygon polygon,Vector3 point)
        {
            float distance=float.MaxValue;var rings=new List<double[][]>{polygon.exterior};if(polygon.holes!=null)rings.AddRange(polygon.holes);
            var p=new Vector2(point.x,point.z);
            foreach(var ring in rings)for(int i=1;i<ring.Length;i++)
            {var a=new Vector2((float)ring[i-1][0],(float)ring[i-1][1]);var b=new Vector2((float)ring[i][0],(float)ring[i][1]);var ab=b-a;float t=ab.sqrMagnitude>0?Mathf.Clamp01(Vector2.Dot(p-a,ab)/ab.sqrMagnitude):0;distance=Mathf.Min(distance,Vector2.Distance(p,a+t*ab));}
            return distance;
        }
    }
}
