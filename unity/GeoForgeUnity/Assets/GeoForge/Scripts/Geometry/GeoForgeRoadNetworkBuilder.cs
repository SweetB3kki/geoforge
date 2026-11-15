using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using UnityEngine;

namespace GeoForge
{
    [Serializable]
    public sealed class GeoForgeRoadGeometrySettings
    {
        [Min(0)] public float pointToleranceMeters = 0.05f;
        [Min(0)] public float collinearToleranceMeters = 0.02f;
        [Min(0)] public float roadWidthTransitionLengthMeters = 10f;
        [Range(0, 60)] public float continuityAngleDegrees = 30f;
        [Min(0.1f)] public float maximumJunctionRadiusMeters = 12f;
        [Min(0)] public float layerHeightMeters = 0.75f;
        [Min(0)] public float structureOffsetMeters = 0.25f;

        public void Validate()
        {
            foreach (float value in new[] {pointToleranceMeters, collinearToleranceMeters,
                roadWidthTransitionLengthMeters, continuityAngleDegrees, maximumJunctionRadiusMeters,
                layerHeightMeters, structureOffsetMeters})
                if (float.IsNaN(value) || float.IsInfinity(value) || value < 0)
                    throw new ArgumentException("Road geometry settings must be finite and nonnegative.");
            if (continuityAngleDegrees > 60 || maximumJunctionRadiusMeters < 0.1f)
                throw new ArgumentException("Invalid road continuity angle or junction radius.");
        }
    }

    /// <summary>Rendering-only network. Never mutates JSON roads or merges source entities.</summary>
    public sealed class GeoForgeRoadNetworkBuilder
    {
        public sealed class Junction
        {
            public Vector3 Position;
            public readonly List<string> ConnectedRoadIds = new List<string>();
            public readonly List<float> ConnectedWidths = new List<float>();
            public readonly List<Vector3> ConnectedDirections = new List<Vector3>();
            public int? Layer;
            public bool Bridge, Tunnel;
            public readonly List<Vector3> Polygon = new List<Vector3>();
        }
        public sealed class Transition
        {
            public Vector3 Position, Start, End;
            public float FirstWidth, SharedWidth, SecondWidth;
        }
        public sealed class Result
        {
            public readonly Dictionary<GeoForgeRoad, GeoForgeMeshData> Meshes = new Dictionary<GeoForgeRoad, GeoForgeMeshData>();
            public readonly Dictionary<GeoForgeRoad, string> Errors = new Dictionary<GeoForgeRoad, string>();
            public readonly List<Junction> Junctions = new List<Junction>();
            public readonly List<Transition> Transitions = new List<Transition>();
            public readonly List<List<Vector3>> Centerlines = new List<List<Vector3>>();
            public int TerminalCaps, LayerSeparatedRoads, RemovedPoints;
            public GeoForgeMeshData Mesh(GeoForgeRoad road)
            {
                if (road == null) throw new ArgumentException("Null road.");
                if (Errors.TryGetValue(road, out var error)) throw new ArgumentException(error);
                return Meshes[road];
            }
        }
        private sealed class Vertex
        {
            public Vector3 P;
            public string Key;
            public bool Protected;
        }
        private sealed class Span
        {
            public GeoForgeRoad Road;
            public List<Vector3> Points;
            public float[] Distances;
            public float Length => Distances[Distances.Length - 1];
            public Arm Start, End;
        }
        private sealed class Arm
        {
            public Span Span;
            public bool Start;
            public Vector3 Direction, SeamDirection;
            public float Trim, Width, Zone;
            public bool Cap;
            public float Available => Span.Length * 0.4f;
            public Vector3 Center(float distance) => Sample(Span, Start ? distance : Span.Length - distance);
        }
        private readonly GeoForgeRoadGeometrySettings settings;
        public GeoForgeRoadNetworkBuilder(GeoForgeRoadGeometrySettings settings)
        { this.settings = settings ?? new GeoForgeRoadGeometrySettings(); this.settings.Validate(); }

        public static float Elevation(GeoForgeRoad road, GeoForgeRoadGeometrySettings settings)
        {
            return 0.03f + (road.layer ?? 0) * settings.layerHeightMeters +
                (road.bridge ? settings.structureOffsetMeters : 0) -
                (road.tunnel ? settings.structureOffsetMeters : 0) +
                (road.road_subtype == "crossing" ? 0.015f : 0);
        }
        public static bool Automotive(GeoForgeRoad road)
        {
            if (road.road_category != "automotive") return false;
            switch (road.road_type)
            {
                case "motorway": case "trunk": case "primary": case "secondary": case "tertiary":
                case "motorway_link": case "trunk_link": case "primary_link": case "secondary_link": case "tertiary_link":
                case "residential": case "living_street": case "unclassified": case "service": return true;
                default: return false;
            }
        }
        public static bool Continuity(GeoForgeRoad a, GeoForgeRoad b)
        {
            if (!Automotive(a) || !Automotive(b) || a.layer == null || a.layer != b.layer ||
                a.bridge != b.bridge || a.tunnel != b.tunnel) return false;
            if (a.road_type == b.road_type) return true;
            string x = a.road_type, y = b.road_type;
            if (x == y + "_link" || y == x + "_link") return true;
            return Pair(x,y,"primary","secondary") || Pair(x,y,"secondary","tertiary") ||
                Pair(x,y,"tertiary","residential") || Pair(x,y,"residential","service");
        }
        private static bool Pair(string x, string y, string a, string b) => (x == a && y == b) || (x == b && y == a);
        private static string Key(GeoForgeRoad road, int i)
        {
            // Use exported topology IDs when available; legacy files use the same micrometer coordinate key.
            // Never snap nearby carriageways. Structure is part of the key even for external node IDs.
            string position = road.node_ids != null && road.node_ids.Count == road.path.Length && !string.IsNullOrEmpty(road.node_ids[i])
                ? road.node_ids[i] : string.Join(",", road.path[i].Select(v => Math.Round(v, 6).ToString("R", CultureInfo.InvariantCulture)));
            return position + "|" + (road.layer?.ToString(CultureInfo.InvariantCulture) ?? "unknown/" + road.id) + "|" + road.bridge + "|" + road.tunnel;
        }

        public Result Build(IList<GeoForgeRoad> roads)
        {
            var result = new Result();
            var paths = new Dictionary<GeoForgeRoad, List<Vertex>>();
            var owners = new Dictionary<string, HashSet<GeoForgeRoad>>();
            foreach (var road in roads)
            {
                if (road == null) continue;
                try
                {
                    if (road.path == null || road.path.Length < 2 || !GeoForgeCoordinateConverter.IsFinite(road.width) || road.width <= 0 || road.width > 10000)
                        throw new ArgumentException("Road requires a path and positive finite width.");
                    var path = new List<Vertex>();
                    for (int i = 0; i < road.path.Length; i++)
                    {
                        var p = GeoForgeCoordinateConverter.GeoForgeToUnity(road.path[i]);
                        p.y = Elevation(road, settings);
                        path.Add(new Vertex {P = p, Key = Key(road, i)});
                    }
                    paths.Add(road, path);
                    foreach (var v in path)
                    {
                        string key = road.road_category + "|" + v.Key;
                        if (!owners.TryGetValue(key, out var set)) owners[key] = set = new HashSet<GeoForgeRoad>();
                        set.Add(road);
                    }
                }
                catch (Exception ex) { result.Errors[road] = ex.Message; }
            }
            var spans = new List<Span>();
            var nodes = new Dictionary<string, List<Arm>>();
            foreach (var entry in paths)
            {
                var road = entry.Key; var path = entry.Value;
                for (int i = 0; i < path.Count; i++) path[i].Protected = i == 0 || i == path.Count - 1 ||
                    (owners.TryGetValue(road.road_category + "|" + path[i].Key, out var set) && set.Count > 1);
                int before = path.Count;
                Normalize(path);
                result.RemovedPoints += before - path.Count;
                if (path.Count < 2) { result.Errors[road] = "Road has fewer than two distinct points."; continue; }
                result.Meshes[road] = new GeoForgeMeshData();
                result.Centerlines.Add(path.Select(v => v.P).ToList());
                if (road.layer.GetValueOrDefault() != 0 || road.bridge || road.tunnel) result.LayerSeparatedRoads++;
                int start = 0;
                for (int i = 1; i < path.Count; i++)
                {
                    if (i != path.Count - 1 && (!Automotive(road) || !path[i].Protected)) continue;
                    var points = path.GetRange(start, i - start + 1).Select(v => v.P).ToList();
                    var span = new Span {Road = road, Points = points, Distances = new float[points.Count]};
                    for (int j = 1; j < points.Count; j++) span.Distances[j] = span.Distances[j-1] + Vector3.Distance(points[j-1], points[j]);
                    if (span.Length < 1e-5f) { start = i; continue; }
                    span.Start = MakeArm(span, true); span.End = MakeArm(span, false); spans.Add(span);
                    if (Automotive(road))
                    {
                        AddArm(nodes, path[start].Key, span.Start); AddArm(nodes, path[i].Key, span.End);
                    }
                    else if (path[0].Key != path[path.Count-1].Key)
                    {
                        span.Start.Cap = owners[road.road_category + "|" + path[0].Key].Count == 1;
                        span.End.Cap = owners[road.road_category + "|" + path[path.Count-1].Key].Count == 1;
                    }
                    else
                    {
                        span.Start.SeamDirection = (span.Start.Direction - span.End.Direction).normalized;
                        span.End.SeamDirection = -span.Start.SeamDirection;
                    }
                    start = i;
                }
            }
            var patchNodes = new List<List<Arm>>();
            foreach (var arms in nodes.Values)
            {
                if (arms.Count == 1) { arms[0].Cap = true; continue; }
                float angle = arms.Count == 2 ? Vector3.Angle(arms[0].Direction, -arms[1].Direction) : 180;
                if (arms.Count == 2 && angle <= settings.continuityAngleDegrees)
                {
                    var a = arms[0]; var b = arms[1];
                    // A common seam also removes tiny cracks where straight pieces meet at a slight angle.
                    var direction = (a.Direction - b.Direction).normalized;
                    a.SeamDirection = direction; b.SeamDirection = -direction;
                    if (Continuity(a.Span.Road, b.Span.Road) && Math.Abs(a.Width - b.Width) > 0.01f && settings.roadWidthTransitionLengthMeters > 0)
                    {
                        float first = a.Width, second = b.Width, shared = (first + second) * 0.5f;
                        a.Width = b.Width = shared;
                        a.Zone = Mathf.Min(settings.roadWidthTransitionLengthMeters, a.Available);
                        b.Zone = Mathf.Min(settings.roadWidthTransitionLengthMeters, b.Available);
                        result.Transitions.Add(new Transition {Position = a.Center(0), Start = a.Center(a.Zone), End = b.Center(b.Zone),
                            FirstWidth = first, SharedWidth = shared, SecondWidth = second});
                    }
                }
                else
                {
                    // Limit each cut to its first centerline edge and 40% of the span, so nearby junctions cannot consume a road.
                    float radius = Mathf.Min(settings.maximumJunctionRadiusMeters, arms.Max(a => a.Width) * 0.65f + 0.5f);
                    foreach (var arm in arms)
                    {
                        float firstEdge = arm.Start ? arm.Span.Distances[1] : arm.Span.Length - arm.Span.Distances[arm.Span.Distances.Length-2];
                        arm.Trim = Mathf.Min(radius, arm.Available, firstEdge * 0.8f);
                    }
                    patchNodes.Add(arms);
                }
            }
            foreach (var span in spans) BuildSpan(span, result);
            foreach (var arms in patchNodes) BuildPatch(arms, result);
            return result;
        }

        private void Normalize(List<Vertex> path)
        {
            for (int i = 1; i < path.Count;)
            {
                float distance = Vector3.Distance(path[i-1].P, path[i].P);
                if (distance < 1e-5f) { path[i].Protected |= path[i-1].Protected; path.RemoveAt(i-1); if (i > 1) i--; }
                else if (distance < settings.pointToleranceMeters && !path[i].Protected) path.RemoveAt(i);
                else if (distance < settings.pointToleranceMeters && !path[i-1].Protected) { path.RemoveAt(i-1); if (i > 1) i--; }
                else i++;
            }
            // Conservative local simplification: keep all endpoints/shared topology vertices, and limit both
            // perpendicular deviation AND removed detour. Never collapse a hairpin or real corner.
            for (int i = path.Count - 2; i > 0; i--)
            {
                if (path[i].Protected) continue;
                var a = path[i-1].P; var b = path[i].P; var c = path[i+1].P;
                var ac = c-a; float length = ac.magnitude;
                if (length < 1e-5f) continue;
                float t = Vector3.Dot(b-a,ac) / (length*length);
                if (t <= 0 || t >= 1) continue;
                if (Vector3.Distance(b,a+t*ac) <= settings.collinearToleranceMeters &&
                    Vector3.Distance(a,b)+Vector3.Distance(b,c)-length <= settings.collinearToleranceMeters)
                    path.RemoveAt(i);
            }
        }
        private static Arm MakeArm(Span span, bool start)
        {
            var p = span.Points;
            var direction = start ? (p[1]-p[0]).normalized : (p[p.Count-2]-p[p.Count-1]).normalized;
            return new Arm {Span = span, Start = start, Direction = direction, SeamDirection = direction, Width = (float)span.Road.width};
        }
        private static void AddArm(Dictionary<string,List<Arm>> nodes, string key, Arm arm)
        { if (!nodes.TryGetValue(key,out var arms)) nodes[key] = arms = new List<Arm>(); arms.Add(arm); }
        private static Vector3 Sample(Span span, float distance)
        {
            for (int i = 1; i < span.Points.Count; i++)
                if (distance <= span.Distances[i]) return Vector3.Lerp(span.Points[i-1],span.Points[i],
                    (distance-span.Distances[i-1])/(span.Distances[i]-span.Distances[i-1]));
            return span.Points[span.Points.Count-1];
        }
        private static Vector3 Normal(Vector3 direction) => new Vector3(-direction.z,0,direction.x);
        private static float WidthAt(Span span, float distance)
        {
            if (span.Start.Zone > 0 && distance < span.Start.Zone)
                return Mathf.Lerp(span.Start.Width,(float)span.Road.width,distance/span.Start.Zone);
            float endDistance = span.Length-distance;
            if (span.End.Zone > 0 && endDistance < span.End.Zone)
                return Mathf.Lerp(span.End.Width,(float)span.Road.width,endDistance/span.End.Zone);
            return (float)span.Road.width;
        }
        private static void BuildSpan(Span span, Result result)
        {
            float start = span.Start.Trim, end = span.Length-span.End.Trim;
            var distances = new List<float> {start,end};
            distances.AddRange(span.Distances.Where(d => d > start && d < end));
            foreach (float d in new[] {span.Start.Zone, span.Length-span.End.Zone}) if (d > start && d < end) distances.Add(d);
            distances = distances.Distinct().OrderBy(d => d).ToList();
            var mesh = result.Meshes[span.Road];
            var points = distances.Select(d => Sample(span,d)).ToList();
            int offset = mesh.Vertices.Count;
            for (int i = 0; i < points.Count; i++)
            {
                Vector3 normal; float scale = 1;
                if (i == 0) normal = Normal(span.Start.Trim > 0 ? span.Start.Direction : span.Start.SeamDirection);
                else if (i == points.Count-1) normal = -Normal(span.End.Trim > 0 ? span.End.Direction : span.End.SeamDirection);
                else
                {
                    var incoming = Normal((points[i]-points[i-1]).normalized);
                    var outgoing = Normal((points[i+1]-points[i]).normalized);
                    normal = (incoming+outgoing).normalized;
                    if (normal.sqrMagnitude < 0.01f) normal = outgoing;
                    scale = Mathf.Min(2f,1f/Mathf.Max(0.01f,Vector3.Dot(normal,outgoing)));
                }
                float half = WidthAt(span,distances[i]) * 0.5f;
                mesh.Vertices.Add(points[i]+normal*half*scale); mesh.Vertices.Add(points[i]-normal*half*scale);
                if (i > 0)
                {
                    int k = offset+2*i;
                    mesh.AddUpTriangle(k-2,k,k-1); mesh.AddUpTriangle(k-1,k,k+1);
                }
            }
            foreach (var arm in new[] {span.Start,span.End}) if (arm.Cap)
            {
                Cap(mesh,arm.Center(0),-arm.Direction,arm.Width*0.5f,Mathf.Min(0.5f,span.Length*0.25f));
                result.TerminalCaps++;
            }
        }
        private static void Cap(GeoForgeMeshData mesh, Vector3 p, Vector3 outward, float halfWidth, float depth)
        {
            int start = mesh.Vertices.Count; mesh.Vertices.Add(p);
            var side = Normal(outward);
            for (int i = 0; i <= 8; i++)
            {
                float angle = i*Mathf.PI/8;
                mesh.Vertices.Add(p+side*(Mathf.Cos(angle)*halfWidth)+outward*(Mathf.Sin(angle)*depth));
                if (i > 0) mesh.AddUpTriangle(start,start+i,start+i+1);
            }
        }
        private static float Cross(Vector3 a, Vector3 b, Vector3 c) => (b.x-a.x)*(c.z-a.z)-(b.z-a.z)*(c.x-a.x);
        private static List<Vector3> Hull(List<Vector3> points)
        {
            var sorted = points.Distinct().OrderBy(p => p.x).ThenBy(p => p.z).ToList();
            var hull = new List<Vector3>();
            foreach (var p in sorted)
            { while (hull.Count >= 2 && Cross(hull[hull.Count-2],hull[hull.Count-1],p) <= 0) hull.RemoveAt(hull.Count-1); hull.Add(p); }
            int lower = hull.Count;
            for (int i = sorted.Count-2; i >= 0; i--)
            { var p=sorted[i]; while (hull.Count > lower && Cross(hull[hull.Count-2],hull[hull.Count-1],p) <= 0) hull.RemoveAt(hull.Count-1); hull.Add(p); }
            if (hull.Count > 1) hull.RemoveAt(hull.Count-1);
            return hull;
        }
        private static int Rank(GeoForgeRoad road)
        {
            switch (road.road_type)
            {
                case "motorway": case "trunk": return 0;
                case "primary": return 1;
                case "secondary": return 2;
                case "tertiary": return 3;
                case "residential": case "unclassified": case "living_street": return 4;
                default: return 5;
            }
        }
        private static void BuildPatch(List<Arm> arms, Result result)
        {
            var road = arms.OrderBy(a => Rank(a.Span.Road)).ThenBy(a => a.Span.Road.id,StringComparer.Ordinal).First().Span.Road;
            var junction = new Junction {Position = arms[0].Center(0), Layer = road.layer, Bridge = road.bridge, Tunnel = road.tunnel};
            var points = new List<Vector3>();
            foreach (var arm in arms)
            {
                var center = arm.Center(arm.Trim); var side = Normal(arm.Direction)*arm.Width*0.5f;
                points.Add(center+side); points.Add(center-side);
                junction.ConnectedRoadIds.Add(arm.Span.Road.id); junction.ConnectedWidths.Add(arm.Width); junction.ConnectedDirections.Add(arm.Direction);
            }
            junction.Polygon.AddRange(Hull(points));
            if (junction.Polygon.Count < 3) return;
            // Stored in the highest-class incident road's mesh: material is shared, no extra scene objects.
            var mesh = result.Meshes[road]; int offset = mesh.Vertices.Count;
            mesh.Vertices.AddRange(junction.Polygon);
            for (int i = 1; i < junction.Polygon.Count-1; i++) mesh.AddUpTriangle(offset,offset+i,offset+i+1);
            result.Junctions.Add(junction);
        }
    }
}
