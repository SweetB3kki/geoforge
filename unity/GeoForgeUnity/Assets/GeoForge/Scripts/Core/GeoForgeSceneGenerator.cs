using System;
using System.Collections.Generic;
using System.Linq;
using System.Diagnostics;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace GeoForge
{
    public sealed class GeoForgeSceneGenerator : MonoBehaviour
    {
        [Tooltip("Absolute path or relative to the Unity project folder.")]
        public string sceneJsonPath = "../../output/audit-v041/sevastopol/scene.json";
        public Material buildingMaterial, roadMaterial, waterMaterial, greenMaterial;
        public Material pedestrianMaterial, cycleMaterial, trackMaterial, otherRoadMaterial;
        public Material motorwayMaterial, primaryMaterial, secondaryMaterial, tertiaryMaterial, serviceMaterial, linkMaterial, stepsMaterial, crossingMaterial;
        public bool ShowAutomotiveRoads = true, ShowPedestrianPaths = true, ShowCyclePaths = true, ShowSteps = true, ShowTracks = true;
        private readonly Dictionary<string,Material> roadMaterials = new Dictionary<string,Material>();
        public GeoForgeRoadGeometrySettings roadGeometry = new GeoForgeRoadGeometrySettings();
        public bool ShowRoadJunctions, ShowRoadTransitions, ShowRoadCenterlines;
        public bool enableBuildingFoundations=true,ShowBuildingTerrainAudit,ShowRoadTerrainAudit,ShowTerrainWireframe,ShowWaterDebug;
        public bool ShowRawRoads,ShowProcessedRoads,ShowLostRoads,ShowFilteredRoads,ShowCoastline;
        public float foundationThresholdMeters=0.3f,maxFoundationDepthMeters=12;
        public Material foundationMaterial;
        private Material foundationShared;
        public bool useLocalRoadSections=false;
        public GeoForgeRoadbedSettings roadbed=new GeoForgeRoadbedSettings();
        private GeoForgeRoadbed derivedRoadbed;
        public GeoForgeConformSettings terrainConform=new GeoForgeConformSettings();
        public readonly List<GeoForgeBuildingFit> BuildingAudit=new List<GeoForgeBuildingFit>();
        public readonly List<GeoForgeSurfaceQuality> SurfaceAudit=new List<GeoForgeSurfaceQuality>();
        [NonSerialized] public GeoForgeRoadNetworkBuilder.Result RoadNetwork;
        private readonly Dictionary<GeoForgeRoad,GeoForgeMeshData> profiledRoadMeshes=new Dictionary<GeoForgeRoad,GeoForgeMeshData>();
        private readonly List<GeoForgeMeshData> groundReplacements=new List<GeoForgeMeshData>();
        public GeoForgeRoadBanks.Result RoadBankAudit { get; private set; }
        private bool HasRoadProfiles=>LoadedScene?.roads?.Any(r=>r?.vertical_profile!=null)==true;
        public Material terrainMaterial, buildingRoofMaterial;
        private Material roofShared;
        [NonSerialized] public GeoForgeTerrainSampler TerrainSampler;
        public bool generateWalkableEnvironment = true;
        [NonSerialized] public GeoForgePlayerController Player;
        public bool generateOnStart = true;
        [SerializeField, HideInInspector] private GameObject generatedRoot;
        [NonSerialized] public GeoForgeScene LoadedScene;
        [NonSerialized] public Statistics LastStatistics;
        private readonly List<Material> ownedMaterials = new List<Material>();

        [Serializable]
        public sealed class Statistics
        {
            public int buildings, buildingsFailed, roads, roadsFailed, water, waterFailed, green, greenFailed;
            public int buildingParents, buildingParts;
            public int roadsHidden, automotive, pedestrian, cycle, steps, tracks, crossings, service;
            public int logicalRoads, widthTransitions, junctionsDetected, junctionPatches, terminalCaps, layerSeparatedRoads, normalizedPointsRemoved;
            public long terrainMilliseconds, buildingsMilliseconds, roadsMilliseconds;
            public int terrainResolution;
            public float terrainMin,terrainMax;
            public int flatRoofs,gabledRoofs,hippedRoofs,roofFallbacks;
            public int colliders;
            public bool playerSpawned;
            public Vector3 playerSpawn;
            public long vertices, triangles, milliseconds;
            public override string ToString() => $"Scene generation complete\nBuildings generated: {buildings}\nBuildings failed: {buildingsFailed}\n" +
                $"Roads generated: {roads} (hidden: {roadsHidden}, failed: {roadsFailed})\nWater areas generated: {water} (failed: {waterFailed})\n" +
                $"Automotive roads: {automotive}, Pedestrian paths: {pedestrian}, Cycle paths: {cycle}, Steps: {steps}, Tracks: {tracks}, Crossings: {crossings}, Service roads: {service}\n" +
                $"Terrain: {terrainResolution} nodes/axis, local height {terrainMin:F2}..{terrainMax:F2} m, colliders: {colliders}, player: {playerSpawned} at {playerSpawn}\n" +
                $"Terrain / buildings / roads: {terrainMilliseconds} / {buildingsMilliseconds} / {roadsMilliseconds} ms\n" +
                $"Logical roads: {logicalRoads}, Width transitions generated: {widthTransitions}, Junctions detected: {junctionsDetected}, Junction patches generated: {junctionPatches}\n" +
                $"Terminal caps: {terminalCaps}, Layer-separated roads: {layerSeparatedRoads}, Normalized points removed: {normalizedPointsRemoved}, Failed road meshes: {roadsFailed}\n" +
                $"Green areas generated: {green} (failed: {greenFailed})\nVertices: {vertices}\nTriangles: {triangles}\nGeneration time: {milliseconds} ms";
        }

        [ContextMenu("LoadScene")]
        public void LoadScene()
        {
            LoadedScene = null;
            try { LoadedScene = GeoForgeJsonLoader.Load(sceneJsonPath); }
            catch (Exception ex) { Debug.LogError(ex.Message, this); }
        }

        [ContextMenu("GenerateScene")]
        public void GenerateScene()
        {
            LoadScene();
            if (LoadedScene == null) return; // Preserve previous output if file cannot be loaded.
            GenerateLoadedScene();
        }

        /// <summary>Public seam for deterministic tests. Input file loading is separate.</summary>
        public void GenerateLoadedScene()
        {
            if (LoadedScene == null) throw new InvalidOperationException("Load a scene first.");
            var timer = Stopwatch.StartNew();
            ClearGeneratedScene();
            LastStatistics = new Statistics();
            generatedRoot = new GameObject("GeoForgeGenerated") { hideFlags = HideFlags.DontSave };
            // Keep the data's world-space positions even when the importer object is moved.
            generatedRoot.transform.SetParent(transform, false);
            generatedRoot.transform.position = Vector3.zero;
            generatedRoot.transform.rotation = Quaternion.identity;
            generatedRoot.transform.localScale = Vector3.one;
            if (transform.lossyScale != Vector3.one)
            {
                ClearGeneratedScene();
                throw new InvalidOperationException("GeoForgeSceneGenerator must have unit scale, including its ancestors.");
            }
            TerrainSampler = new GeoForgeTerrainSampler(LoadedScene);
            var stage=Stopwatch.StartNew();
            if(TerrainSampler.Available){if(!HasRoadProfiles)GenerateTerrain();}
            else if (generateWalkableEnvironment && LoadedScene.bounds != null)
                GeoForgeCollisionSetup.FlatGround(generatedRoot.transform, LoadedScene.bounds);
            LastStatistics.terrainMilliseconds=stage.ElapsedMilliseconds;
            stage.Restart();GenerateBuildings();LastStatistics.buildingsMilliseconds=stage.ElapsedMilliseconds;
            stage.Restart();GenerateRoads();LastStatistics.roadsMilliseconds=Math.Max(0,stage.ElapsedMilliseconds-(HasRoadProfiles?LastStatistics.terrainMilliseconds:0));
            GenerateAreas();
            if (generateWalkableEnvironment && LoadedScene.bounds != null)
            {
                GeoForgeWorldBoundary.Create(generatedRoot.transform, LoadedScene, TerrainSampler.Available?(float)TerrainSampler.Data.min_height-20:-20, TerrainSampler.Available?(float)TerrainSampler.Data.max_height+100:100);
                try
                {
                    Player = GeoForgeSpawnManager.Create(generatedRoot.transform, LoadedScene, TerrainSampler.SampleHeight).GetComponent<GeoForgePlayerController>();
                    LastStatistics.playerSpawned = true; LastStatistics.playerSpawn = Player.safeSpawn;
                }
                catch (Exception ex) { Debug.LogWarning("GeoForge spawn: " + ex.Message, this); }
                LastStatistics.colliders = generatedRoot.GetComponentsInChildren<Collider>().Length;
            }
            timer.Stop(); LastStatistics.milliseconds = timer.ElapsedMilliseconds;
            Debug.Log(LastStatistics.ToString(), this);
        }

        private void GenerateTerrain()
        {
            RoadBankAudit=null;
            var old=generatedRoot.transform.Find("Terrain");if(old!=null)DestroyGroup(old.gameObject,true);
            var data=GeoForgeTerrainGenerator.BuildVisible(LoadedScene,TerrainSampler,groundReplacements);
            derivedRoadbed=roadbed.enabled&&profiledRoadMeshes.Count>0?new GeoForgeRoadbed(profiledRoadMeshes,roadbed):null;
            if(derivedRoadbed!=null)data=derivedRoadbed.Condition(data);
            var bankLand=data;
            if(derivedRoadbed!=null)data=derivedRoadbed.WithFloors(data);
            var terrain=new GameObject("Terrain");terrain.transform.SetParent(generatedRoot.transform,false);
            Mesh mesh=null;
            if(data.Triangles.Count>0)
            {
                mesh=data.ToMesh("DEM terrain");terrain.AddComponent<MeshFilter>().sharedMesh=mesh;
                terrain.AddComponent<MeshRenderer>().sharedMaterial=MaterialOrDefault(terrainMaterial,new Color(0.46f,0.49f,0.36f));
                LastStatistics.vertices+=mesh.vertexCount;LastStatistics.triangles+=data.Triangles.Count/3;
            }
            if(generateWalkableEnvironment)
            {
                if(groundReplacements.Count==0&&LoadedScene.water_areas.Count==0)
                {if(mesh!=null)terrain.AddComponent<MeshCollider>().sharedMesh=mesh;}
                else
                {
                    var collision=GeoForgeTerrainGenerator.BuildCollision(LoadedScene,TerrainSampler,groundReplacements);
                    if(derivedRoadbed!=null)collision=derivedRoadbed.WithFloors(derivedRoadbed.Condition(collision));
                    if(collision.Triangles.Count>0)terrain.AddComponent<MeshCollider>().sharedMesh=collision.ToMesh("Derived terrain collision surface");
                }
            }
            if(groundReplacements.Count>0)
            {
                var surfaces=profiledRoadMeshes.Where(p=>!p.Key.bridge&&!p.Key.tunnel&&(p.Key.layer??0)==0).Select(p=>p.Value);
                RoadBankAudit=GeoForgeRoadBanks.Build(bankLand,groundReplacements,surfaces);
                if(RoadBankAudit.Mesh.Triangles.Count>0)
                {
                    var banks=new GameObject("RoadBanks");banks.transform.SetParent(terrain.transform,false);
                    var bankMesh=RoadBankAudit.Mesh.ToMesh("Derived road cut edges");
                    if(generateWalkableEnvironment)
                    {
                        // The large double-sided bank mesh triggers PhysX's fast
                        // midphase warning on the Moscow fixture. Set cooking
                        // options before attaching a MeshFilter to avoid an
                        // implicit cook with the default options.
                        var collider=banks.AddComponent<MeshCollider>();
                        collider.cookingOptions&=~MeshColliderCookingOptions.UseFastMidphase;
                        collider.sharedMesh=bankMesh;
                    }
                    banks.AddComponent<MeshFilter>().sharedMesh=bankMesh;
                    banks.AddComponent<MeshRenderer>().sharedMaterial=terrain.GetComponent<MeshRenderer>().sharedMaterial;
                    LastStatistics.vertices+=bankMesh.vertexCount;LastStatistics.triangles+=RoadBankAudit.Mesh.Triangles.Count/3;
                }
                if(RoadBankAudit.MissingRoadSurfaceMeters>0.02)
                    Debug.LogWarning("Road bank edges without a road surface: "+RoadBankAudit.MissingRoadSurfaceMeters+" m",this);
            }
            LastStatistics.terrainResolution=TerrainSampler.Data.resolution_x;
            LastStatistics.terrainMin=(float)TerrainSampler.Data.min_height;LastStatistics.terrainMax=(float)TerrainSampler.Data.max_height;
        }
        public void GenerateBuildings()
        {
            RequireRoot();
            BuildingAudit.Clear();foundationShared=MaterialOrDefault(foundationMaterial,new Color(0.38f,0.36f,0.33f));
            roofShared=MaterialOrDefault(buildingRoofMaterial,Color.white);
            LastStatistics.flatRoofs=LastStatistics.gabledRoofs=LastStatistics.hippedRoofs=LastStatistics.roofFallbacks=0;
            LastStatistics.buildingParents=LoadedScene.buildings.Count;
            LastStatistics.buildingParts=LoadedScene.buildings.Sum(b=>b?.parts?.Count??0);
            GenerateGroup("Buildings", GeoForgeBuildingVolumes.Expand(LoadedScene.buildings), b => b?.id, BuildPlacedBuilding,
                MaterialOrDefault(buildingMaterial, new Color(0.67f,0.59f,0.47f)), out LastStatistics.buildings, out LastStatistics.buildingsFailed);
        }
        [ContextMenu("GenerateRoads")]
        public void GenerateRoads()
        {
            RequireRoot();
            if(roadMaterials.Count==0)
            {
                roadMaterials["automotive"]=MaterialOrDefault(roadMaterial,new Color(0.43f,0.47f,0.51f));
                roadMaterials["motorway"]=MaterialOrDefault(motorwayMaterial,new Color(0.18f,0.22f,0.28f));
                roadMaterials["primary"]=MaterialOrDefault(primaryMaterial,new Color(0.24f,0.29f,0.36f));
                roadMaterials["secondary"]=MaterialOrDefault(secondaryMaterial,new Color(0.32f,0.38f,0.45f));
                roadMaterials["tertiary"]=MaterialOrDefault(tertiaryMaterial,new Color(0.38f,0.43f,0.48f));
                roadMaterials["service"]=MaterialOrDefault(serviceMaterial,new Color(0.58f,0.61f,0.57f));
                roadMaterials["link"]=MaterialOrDefault(linkMaterial,new Color(0.49f,0.54f,0.59f));
                roadMaterials["steps"]=MaterialOrDefault(stepsMaterial,new Color(0.55f,0.39f,0.51f));
                roadMaterials["crossing"]=MaterialOrDefault(crossingMaterial,new Color(0.78f,0.64f,0.35f));
                roadMaterials["pedestrian"]=MaterialOrDefault(pedestrianMaterial,new Color(0.58f,0.51f,0.40f));
                roadMaterials["cycle"]=MaterialOrDefault(cycleMaterial,new Color(0.28f,0.43f,0.46f));
                roadMaterials["track"]=MaterialOrDefault(trackMaterial,new Color(0.40f,0.32f,0.22f));
                roadMaterials["other"]=MaterialOrDefault(otherRoadMaterial,new Color(0.55f,0.55f,0.55f));
            }
            var visible = new List<GeoForgeRoad>();
            LastStatistics.roadsHidden = 0;
            LastStatistics.automotive = LastStatistics.pedestrian = LastStatistics.cycle = LastStatistics.steps = LastStatistics.tracks = LastStatistics.crossings = LastStatistics.service = 0;
            foreach (var road in LoadedScene.roads)
            {
                // Inventory counts are independent of display filters; malformed entries still reach validation.
                if (road != null)
                {
                    switch (road.road_category)
                    {
                        case "automotive": LastStatistics.automotive++; break;
                        case "pedestrian": LastStatistics.pedestrian++; break;
                        case "cycle": LastStatistics.cycle++; break;
                        case "steps": LastStatistics.steps++; break;
                        case "track": LastStatistics.tracks++; break;
                    }
                    if (road.road_subtype == "crossing") LastStatistics.crossings++;
                    if (road.road_type == "service") LastStatistics.service++;
                }
                if (IsRoadVisible(road)) visible.Add(road); else LastStatistics.roadsHidden++;
            }
            RoadNetwork = GeoForgeRoadGenerator.BuildNetwork(visible, roadGeometry);
            profiledRoadMeshes.Clear();groundReplacements.Clear();
            var networkHeights=GeoForgeRoadProfileSurface.CreateNetworkHeights(visible,roadGeometry,useLocalRoadSections);
            foreach(var road in visible.Where(r=>r?.vertical_profile!=null).OrderBy(r=>r.road_category=="automotive"?0:1))
            {
                try
                {
                    var profileTimer=Stopwatch.StartNew();
                    var flat=RoadNetwork.Mesh(road);
                    var placed=GeoForgeRoadProfileSurface.Build(flat,road.vertical_profile,
                        heightSampler:GeoForgeCrossingElevation.Applies(road)?
                            GeoForgeCrossingElevation.Create(road,profiledRoadMeshes,roadGeometry):
                            networkHeights[road],
                        maximumTriangles:200000,maximumHeightErrorMeters:0.005f,minimumAdaptiveEdgeMeters:0.15f,
                        preserveProfileAnchors:!GeoForgeCrossingElevation.Applies(road));
                    profiledRoadMeshes.Add(road,placed);
                    if(profileTimer.ElapsedMilliseconds>2000)Debug.Log("Profile build "+road.id+" "+profileTimer.ElapsedMilliseconds+"ms triangles="+placed.Triangles.Count/3);
                    if(!road.bridge&&!road.tunnel&&(road.layer??0)==0)groundReplacements.Add(flat);
                }
                catch(Exception ex){Debug.LogWarning("Road profile "+road.id+": "+ex.Message,this);}
            }
            GeoForgeRoadProfileSurface.StitchSharedVertices(profiledRoadMeshes);
            LastStatistics.logicalRoads = LoadedScene.roads.Count;
            LastStatistics.widthTransitions = RoadNetwork.Transitions.Count;
            LastStatistics.junctionsDetected = LastStatistics.junctionPatches = RoadNetwork.Junctions.Count;
            LastStatistics.terminalCaps = RoadNetwork.TerminalCaps;
            LastStatistics.layerSeparatedRoads = RoadNetwork.LayerSeparatedRoads;
            LastStatistics.normalizedPointsRemoved = RoadNetwork.RemovedPoints;
            SurfaceAudit.RemoveAll(q=>q.category!="green");
            GenerateGroup("Roads", visible, r => r?.id, r => r.vertical_profile==null?
                AdaptSurface(r.id,r.road_category,RoadNetwork.Mesh(r)):profiledRoadMeshes[r],
                roadMaterials["automotive"], out LastStatistics.roads, out LastStatistics.roadsFailed);
            if(HasRoadProfiles&&TerrainSampler.Available)
            {
                var timer=Stopwatch.StartNew();GenerateTerrain();LastStatistics.terrainMilliseconds=timer.ElapsedMilliseconds;
                if(generatedRoot.transform.Find("Green")!=null)GenerateAreas();
            }
        }
        public bool IsRoadVisible(GeoForgeRoad road)
        {
            if(road?.vertical_profile?.surface_visible==false)return false;
            switch (road?.road_category)
            {
                case "automotive": return ShowAutomotiveRoads;
                case "pedestrian": return ShowPedestrianPaths;
                case "cycle": return ShowCyclePaths;
                case "steps": return ShowSteps;
                case "track": return ShowTracks;
                default: return true;
            }
        }
        public static string RoadStyle(GeoForgeRoad road)
        {
            if (road.road_subtype == "crossing") return "crossing";
            if (road.road_category != "automotive") return road.road_category ?? "automotive";
            switch (road.road_type)
            {
                case "motorway": case "trunk": return "motorway";
                case "primary": return "primary";
                case "secondary": return "secondary";
                case "tertiary": return "tertiary";
                case "service": return "service";
                case "motorway_link": case "trunk_link": case "primary_link": case "secondary_link": case "tertiary_link": return "link";
                default: return "automotive";
            }
        }
        public void GenerateAreas()
        {
            RequireRoot();
            SurfaceAudit.RemoveAll(q=>q.category=="green");
            GenerateGroup("Water", LoadedScene.water_areas, a => a?.id, a => BuildArea(a,"water"),
                MaterialOrDefault(waterMaterial, new Color(0.22f,0.55f,0.77f)), out LastStatistics.water, out LastStatistics.waterFailed);
            GenerateGroup("Green", LoadedScene.green_areas, a => a?.id, a => BuildArea(a,"green"),
                MaterialOrDefault(greenMaterial, new Color(0.35f,0.61f,0.31f)), out LastStatistics.green, out LastStatistics.greenFailed);
        }
        private GeoForgeMeshData BuildPlacedBuilding(GeoForgeBuilding building)
        {
            var volume=GeoForgeBuildingVolumes.Volume(building);
            var mesh=GeoForgeRoofGenerator.Build(volume,out var shape);
            if(shape=="gabled")LastStatistics.gabledRoofs++;else if(shape=="hipped")LastStatistics.hippedRoofs++;else LastStatistics.flatRoofs++;
            var requested=GeoForgeBuildingStyleResolver.Tag(building,"roof:shape");
            if(!string.IsNullOrEmpty(requested)&&requested!="flat"&&shape=="flat")LastStatistics.roofFallbacks++;
            float height=GeoForgeBuildingVolumes.Ground(building,TerrainSampler)+(float)building.min_height;
            BuildingAudit.Add(GeoForgeGeometryQuality.Building(building,TerrainSampler,enableBuildingFoundations&&building.min_height==0,foundationThresholdMeters,maxFoundationDepthMeters));
            for(int i=0;i<mesh.Vertices.Count;i++)mesh.Vertices[i]+=Vector3.up*height;
            return mesh;
        }
        private GeoForgeMeshData BuildArea(GeoForgeArea area, string expected)
        {
            if (area?.area_type != expected) throw new ArgumentException($"Expected {expected} area.");
            var mesh=GeoForgeAreaGenerator.Build(area);
            if(expected=="green")
            {
                return GeoForgeAreaGenerator.RemoveWaterCover(AdaptSurface(area.id,"green",mesh,true),LoadedScene.water_areas);
            }
            float height=GeoForgeWaterLevel.Resolve(area,TerrainSampler);
            for(int i=0;i<mesh.Vertices.Count;i++)mesh.Vertices[i]+=Vector3.up*height;
            return mesh;
        }
        private GeoForgeMeshData AdaptSurface(string id,string category,GeoForgeMeshData source,bool cutGround=false)
        {
            var mesh=GeoForgeAdaptiveSurface.Build(source,TerrainSampler,terrainConform,out int limits);
            if(cutGround&&groundReplacements.Count>0)mesh=GeoForgeGroundCutout.SubtractPreservingPlanes(mesh,groundReplacements);
            if(cutGround&&derivedRoadbed!=null)mesh=derivedRoadbed.Condition(mesh);
            float offset=source.Vertices.Count>0?source.Vertices[0].y:0;
            var quality=GeoForgeGeometryQuality.Surface(id,category,mesh,TerrainSampler,offset,terrainConform.terrainConformToleranceMeters+0.001f);
            quality.limitReached=limits;SurfaceAudit.Add(quality);return mesh;
        }
        private void RequireRoot()
        {
            if (generatedRoot == null || LoadedScene == null) throw new InvalidOperationException("Call GenerateScene first.");
        }
        private void GenerateGroup<T>(string name, List<T> source, Func<T,string> id, Func<T,GeoForgeMeshData> build, Material material, out int generated, out int failed)
        {
            // Category methods replace their previous output, too.
            var old = generatedRoot.transform.Find(name);
            if (old != null) DestroyGroup(old.gameObject, true);
            var group = new GameObject(name); group.transform.SetParent(generatedRoot.transform, false);
            generated = failed = 0;
            foreach (var item in source)
            {
                Mesh mesh = null;
                try
                {
                    var data = build(item);
                    if(data.Triangles.Count==0&&item is GeoForgeArea clippedArea&&clippedArea.area_type=="green"&&(groundReplacements.Count>0||LoadedScene.water_areas.Count>0))continue;
                    mesh = data.ToMesh(id(item) ?? "<unknown>");
                    var child = new GameObject(id(item) ?? "<unknown>");
                    child.transform.SetParent(group.transform, false);
                    child.AddComponent<MeshFilter>().sharedMesh = mesh;
                    if(generateWalkableEnvironment&&item is GeoForgeRoad profiledRoad&&profiledRoad.vertical_profile!=null)
                        child.AddComponent<MeshCollider>().sharedMesh=mesh;
                    if (generateWalkableEnvironment && item is GeoForgeBuilding) GeoForgeCollisionSetup.Building(child, mesh);
                    var renderer=child.AddComponent<MeshRenderer>();
                    renderer.sharedMaterial = item is GeoForgeRoad road ?
                        roadMaterials.TryGetValue(RoadStyle(road),out var categoryMaterial) ? categoryMaterial : roadMaterials["other"] : material;
                    if(item is GeoForgeBuilding building)
                    {
                        var fit=BuildingAudit.Find(q=>q.id==building.id);
                        if(fit!=null&&fit.foundationDepth>0.001f)
                        {
                            var foundation=GeoForgeGeometryQuality.Foundation(building,fit);
                            var fmesh=foundation.ToMesh(building.id+"/foundation");
                            var fg=new GameObject("Foundation");fg.transform.SetParent(child.transform,false);
                            fg.AddComponent<MeshFilter>().sharedMesh=fmesh;fg.AddComponent<MeshRenderer>().sharedMaterial=foundationShared;
                            if(generateWalkableEnvironment)GeoForgeCollisionSetup.Building(fg,fmesh);
                            LastStatistics.vertices+=fmesh.vertexCount;LastStatistics.triangles+=foundation.Triangles.Count/3;
                        }
                        renderer.sharedMaterials=new[]{material,roofShared};
                        var block=new MaterialPropertyBlock();block.SetColor("_Color",GeoForgeBuildingStyleResolver.Wall(building));renderer.SetPropertyBlock(block,0);
                        block.SetColor("_Color",GeoForgeBuildingStyleResolver.Roof(building));renderer.SetPropertyBlock(block,1);
                    }
                    LastStatistics.vertices += mesh.vertexCount; LastStatistics.triangles += data.Triangles.Count / 3;
                    generated++;
                }
                catch (Exception ex)
                {
                    if (mesh != null) DisposeObject(mesh);
                    failed++; Debug.LogWarning($"GeoForge: failed {name} object '{id(item) ?? "<unknown>"}': {ex.Message}", this);
                }
            }
        }
        private Material MaterialOrDefault(Material material, Color color)
        {
            if (material != null) return material;
            var shader = Shader.Find("Legacy Shaders/Diffuse");
            if (shader == null) throw new InvalidOperationException("Built-in diffuse shader missing.");
            var fallback = new Material(shader) { color = color, name = "GeoForge default" };
            ownedMaterials.Add(fallback); return fallback;
        }

        [ContextMenu("ClearGeneratedScene")]
        public void ClearGeneratedScene()
        {
            if (generatedRoot != null) DestroyGroup(generatedRoot, false);
            generatedRoot = null;
            Player = null;
            BuildingAudit.Clear();SurfaceAudit.Clear();
            TerrainSampler = null;
            foreach (var material in ownedMaterials) if (material != null) DisposeObject(material);
            ownedMaterials.Clear();
            roadMaterials.Clear();
            RoadNetwork = null;
            RoadBankAudit = null;
            profiledRoadMeshes.Clear();groundReplacements.Clear();
        }
        private void DestroyGroup(GameObject group, bool subtractStatistics)
        {
            group.SetActive(false); // Destroy is deferred in Play mode: no duplicate visible frame.
            group.transform.SetParent(null);
            var meshes=new HashSet<Mesh>();
            foreach (var filter in group.GetComponentsInChildren<MeshFilter>(true))
            {
                var mesh = filter.sharedMesh;
                if (mesh == null) continue;
                if (subtractStatistics && LastStatistics != null)
                { LastStatistics.vertices -= mesh.vertexCount; LastStatistics.triangles -= mesh.triangles.Length / 3; }
                meshes.Add(mesh);
            }
            foreach(var collider in group.GetComponentsInChildren<MeshCollider>(true))if(collider.sharedMesh!=null)meshes.Add(collider.sharedMesh);
            foreach(var mesh in meshes)DisposeObject(mesh);
            DisposeObject(group);
        }
        private static void DisposeObject(UnityEngine.Object value)
        {
            if (Application.isPlaying) Destroy(value); else DestroyImmediate(value);
        }
        private void OnDrawGizmos()
        {
            if(TerrainSampler!=null&&LoadedScene?.processing_audit?["records"] is Newtonsoft.Json.Linq.JArray records)
            foreach(var record in records)
            {
                bool coast=(string)record["source_tags"]?["natural"]=="coastline";
                string status=(string)record["status"];
                if(!(ShowCoastline&&coast)&&!(record["source_tags"]?["highway"]!=null&&(ShowRawRoads||(ShowLostRoads&&status=="lost")||(ShowFilteredRoads&&status=="filtered"))))continue;
                var geometry=record["raw_geometry_local"];if((string)geometry?["type"]!="LineString")continue;
                var coordinates=geometry["coordinates"];Gizmos.color=coast?Color.blue:status=="lost"?Color.red:status=="filtered"?new Color(1,0.5f,0):Color.gray;
                for(int i=1;i<coordinates.Count();i++)
                {var a=coordinates[i-1];var b=coordinates[i];var p=new Vector3((float)a[0],0,(float)a[1]);var q=new Vector3((float)b[0],0,(float)b[1]);p.y=TerrainSampler.SampleHeight(p.x,p.z)+0.15f;q.y=TerrainSampler.SampleHeight(q.x,q.z)+0.15f;Gizmos.DrawLine(p,q);}
            }
            if(ShowBuildingTerrainAudit)foreach(var q in BuildingAudit)
            {Gizmos.color=q.remainingGap>foundationThresholdMeters?Color.red:Color.yellow;Gizmos.DrawWireCube(q.center,Vector3.one*Mathf.Max(2,q.terrainHeightRange));}
            if(ShowTerrainWireframe&&generatedRoot!=null)
            {var t=generatedRoot.transform.Find("Terrain");if(t!=null&&t.TryGetComponent<MeshFilter>(out var f)){Gizmos.color=Color.gray;Gizmos.DrawWireMesh(f.sharedMesh);}}
            if((ShowRoadTerrainAudit||ShowWaterDebug)&&generatedRoot!=null)
            {
                var t=generatedRoot.transform.Find(ShowWaterDebug?"Water":"Roads");
                if(t!=null)foreach(var f in t.GetComponentsInChildren<MeshFilter>()){Gizmos.color=Color.cyan;Gizmos.DrawWireMesh(f.sharedMesh);}
            }
            if (RoadNetwork == null) return;
            if (ShowRoadCenterlines||ShowProcessedRoads)
            {
                Gizmos.color = Color.cyan;
                foreach (var line in RoadNetwork.Centerlines)
                    for (int i=1;i<line.Count;i++) Gizmos.DrawLine(line[i-1]+Vector3.up*0.1f,line[i]+Vector3.up*0.1f);
            }
            if (ShowRoadJunctions)
            {
                Gizmos.color = Color.magenta;
                foreach (var junction in RoadNetwork.Junctions)
                {
                    Gizmos.DrawWireSphere(junction.Position+Vector3.up*0.1f,0.8f);
                    for (int i=0;i<junction.Polygon.Count;i++)
                        Gizmos.DrawLine(junction.Polygon[i]+Vector3.up*0.1f,junction.Polygon[(i+1)%junction.Polygon.Count]+Vector3.up*0.1f);
                }
            }
            if (ShowRoadTransitions)
            {
                Gizmos.color = Color.yellow;
                foreach (var transition in RoadNetwork.Transitions)
                {
                    Gizmos.DrawLine(transition.Start+Vector3.up*0.15f,transition.Position+Vector3.up*0.15f);
                    Gizmos.DrawLine(transition.Position+Vector3.up*0.15f,transition.End+Vector3.up*0.15f);
                    Gizmos.DrawWireSphere(transition.Position+Vector3.up*0.15f,0.5f);
                }
            }
        }
        private void OnDestroy() { ClearGeneratedScene(); }
        private void Start() { if (generateOnStart) GenerateScene(); }
    }
}
