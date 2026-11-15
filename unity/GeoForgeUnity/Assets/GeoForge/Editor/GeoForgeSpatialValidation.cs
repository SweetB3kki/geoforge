using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Text;
using Newtonsoft.Json;
using UnityEngine;
using UnityEditor.SceneManagement;

namespace GeoForge.Editor
{
    public static partial class GeoForgeBatchValidation
    {
        // Diagnostic only: capture both inputs with identical framing and export
        // actual world vertices. Do not move generated objects for the audit.
        public static void RenderSpatialAudit()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var g=UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();
            var cam=Camera.main;
            g.useLocalRoadSections=Environment.GetEnvironmentVariable("GEOFORGE_G5_LOCAL_SECTIONS")=="1";
            g.roadbed.enabled=Environment.GetEnvironmentVariable("GEOFORGE_G5_ROADBED")=="1";
            try{
                foreach(string city in new[]{"moscow","sevastopol"}){
                    string folder="../../"+(Environment.GetEnvironmentVariable("GEOFORGE_G5_OUTPUT_ROOT")??"output/v05-g5")+"/"+city;
                    var target=JsonConvert.DeserializeObject<double[]>(File.ReadAllText(GeoForgeJsonLoader.ResolvePath(folder+"/focus.json")));
                    foreach(bool after in Environment.GetEnvironmentVariable("GEOFORGE_G5_RENDER_STAGE")=="before"?new[]{false}:new[]{true}){
                        string input=(after?folder:"../../output/v05-g5/before-elevation-20261107/"+city)+"/scene.json";
                        string prefix=folder+(after?"/after":"/before");
                        Render(g,cam,input,prefix);
                        File.Copy(GeoForgeJsonLoader.ResolvePath(prefix+"-3d.png"),
                            GeoForgeJsonLoader.ResolvePath(folder+(after?"/unity-overview.png":"/unity-overview-before.png")),true);
                        cam.orthographic=false;
                        Action<float,float,string> close=(x,z,file)=>{
                            var center=new Vector3(x,g.TerrainSampler.SampleHeight(x,z),z);
                            cam.transform.position=center+new Vector3(26,35,-38);
                            cam.transform.LookAt(center);
                            Capture(cam,GeoForgeJsonLoader.ResolvePath(folder+"/"+file+".png"));
                        };
                        close((float)target[0],(float)target[1],after?"water-after":"water-before");
                        var views=JsonConvert.DeserializeObject<Dictionary<string,double[]>>(File.ReadAllText(GeoForgeJsonLoader.ResolvePath(folder+"/viewpoints.json")));
                        var junction=g.RoadNetwork.Junctions.OrderBy(j=>(j.Position-new Vector3((float)views["junction"][0],0,(float)views["junction"][1])).sqrMagnitude).First();
                        close((float)views["junction"][0],(float)views["junction"][1],after?"unity-junction":"unity-junction-before");
                        close((float)views["crossing"][0],(float)views["crossing"][1],after?"unity-crossing":"unity-crossing-before");
                        var street=new Vector3((float)views["street"][0],(float)views["street"][2],(float)views["street"][1]);
                        cam.transform.position=street;cam.transform.rotation=Quaternion.Euler(3,35,0);
                        Capture(cam,GeoForgeJsonLoader.ResolvePath(folder+(after?"/unity-street.png":"/unity-street-before.png")));
                        if(after){
                            WriteQuality(g,folder+"/unity-quality.json");
                            WriteRoadProfileChecks(g,folder+"/road-profile-render-checks.json");
                            WriteGroundRoadFaces(g,folder);
                            var root=g.transform.Find("GeoForgeGenerated");
                            var controller=root.GetComponentInChildren<CharacterController>(true);
                            var eyes=controller!=null?controller.GetComponentInChildren<Camera>(true):null;
                            File.WriteAllText(GeoForgeJsonLoader.ResolvePath(folder+"/unity-scale.json"),
                                JsonConvert.SerializeObject(new{rootScale=new[]{root.lossyScale.x,root.lossyScale.y,root.lossyScale.z},
                                playerHeight=controller?.height,playerRadius=controller?.radius,eyeHeight=eyes?.transform.localPosition.y,
                                junction=new[]{junction.Position.x,junction.Position.z},junctionRoads=junction.ConnectedRoadIds},Formatting.Indented));
                            using(var writer=new BinaryWriter(File.Create(GeoForgeJsonLoader.ResolvePath(folder+"/unity-faces.bin"))))
                            using(var sha=System.Security.Cryptography.SHA256.Create()){
                                writer.Write(Encoding.ASCII.GetBytes("GFM1"));
                                writer.Write(sha.ComputeHash(File.ReadAllBytes(GeoForgeJsonLoader.ResolvePath(input))));
                                var groups=new[]{"Water","Buildings","Roads","Green"};
                                var items=groups.SelectMany(group=>root.Find(group).Cast<Transform>()
                                    .Select(t=>(id:group+"/"+t.name,t:t,m:t.GetComponent<MeshFilter>()?.sharedMesh)))
                                    .Where(o=>o.m!=null).ToArray();
                                writer.Write(items.Length+2);
                                void Write(string id,Vector3[] vertices,int[] triangles,Transform t){
                                    var key=Encoding.UTF8.GetBytes(id);writer.Write(key.Length);writer.Write(key);
                                    writer.Write(triangles.Length/3);
                                    foreach(int i in triangles){var p=t.TransformPoint(vertices[i]);writer.Write(p.x);writer.Write(p.z);writer.Write(p.y);}
                                }
                                foreach(var item in items)Write(item.id,item.m.vertices,item.m.triangles,item.t);
                                // Isolate water subtraction; the final terrain additionally contains legitimate road cuts.
                                var land=GeoForgeTerrainGenerator.BuildVisible(g.LoadedScene,g.TerrainSampler);
                                Write("Terrain/water-only",land.Vertices.ToArray(),land.Triangles.ToArray(),root);
                                var actualTerrain=root.Find("Terrain");
                                var actualMesh=actualTerrain.GetComponent<MeshFilter>().sharedMesh;
                                Write("Terrain/rendered",actualMesh.vertices,actualMesh.triangles,actualTerrain);
                            }
                        }
                    }
                }
            }finally{
                g.ClearGeneratedScene();g.sceneJsonPath="../../output/multisource-v05/sevastopol/scene.json";
                EditorSceneManager.SaveScene(g.gameObject.scene);
            }
        }
    }
}

