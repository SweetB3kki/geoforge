using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace GeoForge.Editor
{
    public static partial class GeoForgeBatchValidation
    {
        public static void RenderRoadProfilePrototype()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var g=UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();
            var camera=Camera.main;
            foreach(var city in new[]{"sevastopol","moscow"})
            {
                string folder="../../output/multisource-v05/phase-g/"+city;
                Render(g,camera,folder+"/scene.json",folder+"/unity");
                WriteQuality(g,folder+"/unity-quality.json");
                WriteRoadProfileChecks(g,folder+"/road-profile-render-checks.json");
                WriteGroundRoadFaces(g,folder);
                if(city=="sevastopol")WriteJunctionDetailChecks(g,folder);
                CaptureRoadBankDetails(g,camera,folder);
                if(g.LastStatistics.roadsFailed>0)throw new Exception("Profile road meshes failed: "+city);
            }
            g.ClearGeneratedScene();
            g.sceneJsonPath="../../output/multisource-v05/sevastopol/scene.json";
            EditorSceneManager.SaveScene(g.gameObject.scene);
            Debug.Log("Experimental G profile render completed; full acceptance remains pending.");
        }
        public static void ExportGroundRoadFaces()
        {
            GeoForgeProjectSetup.CreateTestScene();
            var g=UnityEngine.Object.FindFirstObjectByType<GeoForgeSceneGenerator>();
            try
            {
                foreach(string city in new[]{"sevastopol","moscow"})
                {
                    string folder="../../output/multisource-v05/phase-g/"+city;
                    g.sceneJsonPath=folder+"/scene.json";g.GenerateScene();
                    if(g.LastStatistics==null||g.LastStatistics.roadsFailed!=0)throw new Exception("Road generation failed: "+city);
                    WriteGroundRoadFaces(g,folder);
                }
            }
            finally
            {
                g.ClearGeneratedScene();g.sceneJsonPath="../../output/multisource-v05/sevastopol/scene.json";
                EditorSceneManager.SaveScene(g.gameObject.scene);
            }
        }
        private static void WriteGroundRoadFaces(GeoForgeSceneGenerator g,string folder)
        {
            var children=g.transform.Find("GeoForgeGenerated/Roads").Cast<Transform>().ToDictionary(t=>t.name,t=>t);
            var roads=g.LoadedScene.roads.Where(r=>r.vertical_profile!=null&&r.vertical_profile.surface_visible&&
                r.road_category=="automotive"&&!r.bridge&&!r.tunnel&&r.layer==0).OrderBy(r=>r.id,StringComparer.Ordinal).ToArray();
            string path=GeoForgeJsonLoader.ResolvePath(folder+"/ground-road-faces.bin");
            using(var w=new BinaryWriter(File.Create(path)))
            using(var sha=System.Security.Cryptography.SHA256.Create())
            {
                w.Write(System.Text.Encoding.ASCII.GetBytes("GFM1"));
                w.Write(sha.ComputeHash(File.ReadAllBytes(GeoForgeJsonLoader.ResolvePath(folder+"/scene.json"))));w.Write(roads.Length);
                foreach(var road in roads)
                {
                    var child=children[road.id];var mesh=child.GetComponent<MeshFilter>().sharedMesh;
                    var vertices=mesh.vertices;var indices=mesh.triangles;
                    var id=System.Text.Encoding.UTF8.GetBytes(road.id);w.Write(id.Length);w.Write(id);w.Write(indices.Length/3);
                    foreach(int index in indices)
                    {
                        var p=g.transform.InverseTransformPoint(child.TransformPoint(vertices[index]));
                        w.Write(p.x);w.Write(p.z);w.Write(p.y);
                    }
                }
            }
        }
        private static void CaptureRoadBankDetails(GeoForgeSceneGenerator g,Camera camera,string folder)
        {
            var mesh=g.RoadBankAudit?.Mesh;if(mesh==null||mesh.Vertices.Count<8)return;
            int selected=0;float highest=-1;
            for(int i=0;i<mesh.Vertices.Count;i+=8)
            {
                var a=mesh.Vertices[i];var b=mesh.Vertices[i+1];
                if(new Vector2(a.x-b.x,a.z-b.z).magnitude<0.1f)continue;
                float height=Math.Max(Math.Abs(a.y-mesh.Vertices[i+3].y),Math.Abs(b.y-mesh.Vertices[i+2].y));
                if(height>highest){highest=height;selected=i;}
            }
            var p=mesh.Vertices[selected];var q=mesh.Vertices[selected+1];
            var target=(p+q+mesh.Vertices[selected+2]+mesh.Vertices[selected+3])/4;
            var normal=new Vector3(q.z-p.z,0,p.x-q.x).normalized;
            var position=camera.transform.position;var rotation=camera.transform.rotation;bool orthographic=camera.orthographic;
            // Buildings can completely occlude this diagnostic close-up. Keep normal overview renders intact.
            var buildings=g.transform.Find("GeoForgeGenerated/Buildings");
            bool buildingsActive=buildings!=null&&buildings.gameObject.activeSelf;
            try
            {
                if(buildings!=null)buildings.gameObject.SetActive(false);
                camera.orthographic=false;
                for(int side=0;side<2;side++)
                {
                    camera.transform.position=target+normal*(side==0?14:-14)+Vector3.up*8;
                    camera.transform.LookAt(target);
                    Capture(camera,GeoForgeJsonLoader.ResolvePath(folder+"/road-bank-detail-"+side+".png"));
                }
                File.WriteAllText(GeoForgeJsonLoader.ResolvePath(folder+"/road-bank-detail.json"),JsonConvert.SerializeObject(new{
                    scope="Two diagnostic views of a high derived vertical road cap, buildings hidden; not a surveyed retaining wall",
                    target=new[]{target.x,target.y,target.z},heightMeters=highest},Formatting.Indented));
            }
            finally{if(buildings!=null)buildings.gameObject.SetActive(buildingsActive);camera.transform.position=position;camera.transform.rotation=rotation;camera.orthographic=orthographic;}
        }
        private static void WriteJunctionDetailChecks(GeoForgeSceneGenerator g,string folder)
        {
            var ids=new[]{"way/325325782/road/0","way/28870943/road/0","way/93634252/road/0"};
            var root=g.transform.Find("GeoForgeGenerated/Roads");var results=new List<object>();
            foreach(var id in ids)
            {
                var road=g.LoadedScene.roads.First(r=>r.id==id);
                var collider=root.Find(id)?.GetComponent<MeshCollider>();
                // IDs contain slashes: Transform.Find interprets them as paths.
                if(collider==null)collider=root.Cast<Transform>().First(t=>t.name==id).GetComponent<MeshCollider>();
                var field=GeoForgeRoadProfileSurface.ConnectedHeight(road,g.LoadedScene.roads,g.roadGeometry);
                int comparisons=0,steps=0;double maxMesh=0,maxField=0;float[] worst=null;
                for(int ix=0;ix<=200;ix++)for(int iz=0;iz<=200;iz++)
                {
                    float x=123.82026f+ix*0.25f,z=407.97413f+iz*0.25f;
                    var ray=new Ray(new Vector3(x,100,z),Vector3.down);
                    if(!collider.Raycast(ray,out var first,1000))continue;
                    foreach(var delta in new[]{new Vector3(0.01f,0,0),new Vector3(0,0,0.01f)})
                    {
                        if(!collider.Raycast(new Ray(ray.origin+delta,Vector3.down),out var second,1000))continue;
                        comparisons++;double step=Math.Abs(first.point.y-second.point.y);
                        if(step>0.02)steps++;
                        if(step>maxMesh){maxMesh=step;worst=new[]{x,z,delta.x,delta.z,first.point.y,second.point.y};}
                        maxField=Math.Max(maxField,Math.Abs(field(x,z)-field(x+delta.x,z+delta.z)));
                    }
                }
                results.Add(new{roadId=id,comparisons,meshStepsOver2cm=steps,maximumMeshStepMeters=maxMesh,
                    maximumHeightFieldStepMeters=maxField,worst});
            }
            string digest;
            using(var sha=System.Security.Cryptography.SHA256.Create())
                digest=BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(GeoForgeJsonLoader.ResolvePath(folder+"/scene.json")))).Replace("-","").ToLowerInvariant();
            File.WriteAllText(GeoForgeJsonLoader.ResolvePath(folder+"/junction-detail-checks.json"),JsonConvert.SerializeObject(new{
                sceneSha256=digest,
                scope="Three Sevastopol roads near the observed defect; 50m square, 0.25m grid, 1cm X/Z probes. " +
                    "Both hits must be on the same collider. Not a full seam or continuous mesh gate.",roads=results},Formatting.Indented));
        }
        private static void WriteRoadProfileChecks(GeoForgeSceneGenerator g,string path)
        {
            var root=g.transform.Find("GeoForgeGenerated");
            var children=root.Find("Roads").Cast<Transform>().ToDictionary(t=>t.name,t=>t);
            var terrain=root.Find("Terrain").GetComponent<MeshCollider>();
            var groundColliders=g.LoadedScene.roads.Where(r=>!r.bridge&&!r.tunnel&&(r.layer??0)==0&&children.ContainsKey(r.id))
                .Select(r=>children[r.id].GetComponent<MeshCollider>()).Where(c=>c!=null).ToArray();
            Physics.SyncTransforms();
            int samples=0,roadHits=0,terrainBlocks=0,missingMeshSamples=0,hiddenTunnels=0;
            int coveredByOtherRoad=0,uncoveredByRoadNetwork=0;
            double maxError=0;var blocked=new List<object>();
            var uncovered=new List<object>();var deviations=new List<(double error,object detail)>();
            var heights=new Dictionary<string,List<(string,float)>>();
            var sampledMeshes=new List<object>();
            var anchorDiagnostics=new List<object>();
            foreach(var road in g.LoadedScene.roads)
            {
                var profile=road.vertical_profile;if(profile==null)continue;
                if(!profile.surface_visible){if(!children.ContainsKey(road.id))hiddenTunnels++;continue;}
                if(!children.TryGetValue(road.id,out var child))continue;
                var collider=child.GetComponent<MeshCollider>();
                if(road.bridge||road.tunnel||(road.layer??0)!=0)continue;
                var meshHeights=new double?[profile.points.Length];
                var hitTriangles=new int[profile.points.Length];
                foreach(var p in profile.points)
                {
                    samples++;
                    var ray=new Ray(new Vector3((float)p[0],(float)g.TerrainSampler.Data.max_height+100,(float)p[1]),Vector3.down);
                    if(!collider.Raycast(ray,out var roadHit,1000))
                    {
                        missingMeshSamples++;
                        bool covered=groundColliders.Any(c=>c.bounds.min.x<=ray.origin.x&&c.bounds.max.x>=ray.origin.x&&
                            c.bounds.min.z<=ray.origin.z&&c.bounds.max.z>=ray.origin.z&&c.Raycast(ray,out _,1000));
                        if(covered)coveredByOtherRoad++;
                        else
                        {
                            uncoveredByRoadNetwork++;
                            int nearbyCovered=0;
                            foreach(float dx in new[]{-0.02f,0,0.02f})foreach(float dz in new[]{-0.02f,0,0.02f})
                            {
                                var check=new Ray(ray.origin+new Vector3(dx,0,dz),Vector3.down);
                                if(groundColliders.Any(c=>c.Raycast(check,out _,1000)))nearbyCovered++;
                            }
                            uncovered.Add(new{id=road.id,category=road.road_category,x=p[0],z=p[1],
                                sampleIndex=Array.IndexOf(profile.points,p),sampleCount=profile.points.Length,nearbyCovered,
                                coveredByFrozenPlanarNetwork=g.RoadNetwork.Meshes.Where(pair=>!pair.Key.bridge&&!pair.Key.tunnel&&(pair.Key.layer??0)==0)
                                    .Any(pair=>ContainsPlanarPoint(pair.Value,p[0],p[1]))});
                        }
                        continue;
                    }
                    roadHits++;
                    meshHeights[Array.IndexOf(profile.points,p)]=roadHit.point.y;
                    hitTriangles[Array.IndexOf(profile.points,p)]=roadHit.triangleIndex;
                    double error=Math.Abs(roadHit.point.y-p[2]-GeoForgeRoadNetworkBuilder.Elevation(road,g.roadGeometry));
                    maxError=Math.Max(maxError,error);
                    if(error>0.02)deviations.Add((error,new{id=road.id,category=road.road_category,x=p[0],z=p[1],
                        sampleIndex=Array.IndexOf(profile.points,p),sampleCount=profile.points.Length,errorMeters=error}));
                    if(terrain!=null&&terrain.Raycast(ray,out var groundHit,1000)&&groundHit.point.y>roadHit.point.y+0.02f)
                    {
                        terrainBlocks++;int nearbyRoadHits=0,nearbyTerrainBlocks=0;
                        foreach(float dx in new[]{-0.02f,0,0.02f})foreach(float dz in new[]{-0.02f,0,0.02f})
                        {
                            var check=new Ray(ray.origin+new Vector3(dx,0,dz),Vector3.down);
                            if(!collider.Raycast(check,out var rh,1000))continue;nearbyRoadHits++;
                            if(terrain.Raycast(check,out var th,1000)&&th.point.y>rh.point.y+0.02f)nearbyTerrainBlocks++;
                        }
                        if(blocked.Count<20)
                        {
                            var indices=terrain.sharedMesh.triangles;var vertices=terrain.sharedMesh.vertices;
                            var a=vertices[indices[groundHit.triangleIndex*3]];
                            var b=vertices[indices[groundHit.triangleIndex*3+1]];
                            var c=vertices[indices[groundHit.triangleIndex*3+2]];
                            double area=Math.Abs((b.x-a.x)*(double)(c.z-a.z)-(b.z-a.z)*(double)(c.x-a.x))/2;
                            blocked.Add(new{id=road.id,x=p[0],z=p[1],profileHeight=p[2],roadHeight=roadHit.point.y,
                                terrainHeight=groundHit.point.y,nearbyRoadHits,nearbyTerrainBlocks,terrainTriangleArea=area,
                                terrainTriangle=new[]{new[]{a.x,a.y,a.z},new[]{b.x,b.y,b.z},new[]{c.x,c.y,c.z}}});
                        }
                    }
                }
                sampledMeshes.Add(new{roadId=road.id,heights=meshHeights});
                var meshVertices=child.GetComponent<MeshFilter>().sharedMesh.vertices;
                var meshIndices=child.GetComponent<MeshFilter>().sharedMesh.triangles;
                for(int i=0;i<profile.points.Length;i++)
                {
                    var p=profile.points[i];if(!meshHeights[i].HasValue||Math.Abs(meshHeights[i].Value-p[2]-GeoForgeRoadNetworkBuilder.Elevation(road,g.roadGeometry))<0.001)continue;
                    var matches=meshVertices.Where(v=>Math.Abs(v.x-(float)p[0])<0.00001f&&Math.Abs(v.z-(float)p[1])<0.00001f).Select(v=>v.y).Distinct().ToArray();
                    var triangle=Enumerable.Range(0,3).Select(j=>meshVertices[meshIndices[hitTriangles[i]*3+j]])
                        .Select(v=>new[]{v.x,v.y,v.z}).ToArray();
                    anchorDiagnostics.Add(new{roadId=road.id,sampleIndex=i,profileHeight=p[2],rayHeight=meshHeights[i],anchorHeights=matches,hitTriangle=triangle});
                }
                if(road.road_category!="automotive")continue;
                foreach(var vertex in child.GetComponent<MeshFilter>().sharedMesh.vertices)
                {
                    string key=Math.Round(vertex.x,3)+"|"+Math.Round(vertex.z,3)+"|"+(road.layer?.ToString()??road.id);
                    if(!heights.TryGetValue(key,out var values)){values=new List<(string,float)>();heights.Add(key,values);}
                    if(!values.Any(v=>v.Item1==road.id))values.Add((road.id,vertex.y));
                }
            }
            var shared=heights.Values.Where(v=>v.Count>1).ToArray();
            var gaps=shared.Select(v=>v.Max(x=>x.Item2)-v.Min(x=>x.Item2)).ToArray();
            string scenePath=Path.Combine(Path.GetDirectoryName(GeoForgeJsonLoader.ResolvePath(path)),"scene.json");
            string sceneSha;
            using(var sha=System.Security.Cryptography.SHA256.Create())
                sceneSha=BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(scenePath))).Replace("-","").ToLowerInvariant();
            File.WriteAllText(GeoForgeJsonLoader.ResolvePath(path),JsonConvert.SerializeObject(new{
                scope="Experimental G; centerline raycasts and coincident automotive vertices only",
                sceneSha256=sceneSha,sampledMeshes,
                anchorDiagnostics,
                roadBanks=g.RoadBankAudit==null?null:new{
                    boundaryEdges=g.RoadBankAudit.BoundaryEdges,
                    surfaceTrianglesScanned=g.RoadBankAudit.SurfaceTrianglesScanned,
                    surfaceTrianglesIndexed=g.RoadBankAudit.SurfaceTrianglesIndexed,
                    segments=g.RoadBankAudit.Segments,
                    inputCapIntervals=g.RoadBankAudit.InputCapIntervals,
                    mergedCapIntervals=g.RoadBankAudit.MergedCapIntervals,
                    simplificationToleranceMeters=g.RoadBankAudit.SimplificationToleranceMeters,
                    maximumSimplificationErrorMeters=g.RoadBankAudit.MaximumSimplificationErrorMeters,
                    triangles=g.RoadBankAudit.Mesh.Triangles.Count/3,
                    missingRoadSurfaceMeters=g.RoadBankAudit.MissingRoadSurfaceMeters,
                    excludedNonRoadEdgeMeters=g.RoadBankAudit.ExcludedNonRoadEdgeMeters,
                    missingRoadSurfaceExamples=g.RoadBankAudit.MissingRoadSurfaceExamples,
                    maximumHeightDifferenceMeters=g.RoadBankAudit.MaximumHeightDifferenceMeters,
                    colliderPresent=root.Find("Terrain/RoadBanks")?.GetComponent<MeshCollider>()!=null},
                samples,roadHits,missingMeshSamples,coveredByOtherRoad,uncoveredByRoadNetwork,terrainBlocks,blockedRoadExamples=blocked,
                maxProfileSampleErrorMeters=maxError,hiddenTunnels,
                uncoveredRoadExamples=uncovered,
                profileSamplesOver2cm=deviations.Count,
                largestProfileDeviations=deviations.OrderByDescending(d=>d.error).Take(20).Select(d=>d.detail).ToArray(),
                sharedAutomotiveVertexLocations=shared.Length,
                sharedVertexGapsOver2cm=gaps.Count(v=>v>0.02f),
                maximumSharedVertexGapMeters=gaps.Length==0?0:gaps.Max(),
                unresolved="Bank geometry cost, bridge approaches/cross sections and complete seam acceptance remain pending"
            },Formatting.Indented));
        }
        private static bool ContainsPlanarPoint(GeoForgeMeshData mesh,double x,double z)
        {
            for(int i=0;i<mesh.Triangles.Count;i+=3)
            {
                var a=mesh.Vertices[mesh.Triangles[i]];var b=mesh.Vertices[mesh.Triangles[i+1]];var c=mesh.Vertices[mesh.Triangles[i+2]];
                double determinant=(b.z-c.z)*(double)(a.x-c.x)+(c.x-b.x)*(double)(a.z-c.z);
                if(Math.Abs(determinant)<1e-12)continue;
                double u=((b.z-c.z)*(x-c.x)+(c.x-b.x)*(z-c.z))/determinant;
                double v=((c.z-a.z)*(x-c.x)+(a.x-c.x)*(z-c.z))/determinant;
                if(u>=-1e-6&&v>=-1e-6&&u+v<=1+1e-6)return true;
            }
            return false;
        }
    }
}
