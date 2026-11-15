using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace GeoForge
{
    /// <summary>Exported local metre profile; points use X=east,Y=north,Z=up.</summary>
    public sealed class GeoForgeRoadVerticalProfile
    {
        public double[][] points;
        public double[] raw_heights;
        public string strategy, bridge_height_method;
        public bool surface_visible = true;
        public bool estimated = true;
    }

    public static class GeoForgeRoadProfileSurface
    {
        public static Dictionary<GeoForgeRoad,Func<float,float,float>> CreateNetworkHeights(IList<GeoForgeRoad> roads,GeoForgeRoadGeometrySettings settings,bool localSections=false)
        {
            var result=new Dictionary<GeoForgeRoad,Func<float,float,float>>();
            var pending=new HashSet<GeoForgeRoad>(roads.Where(r=>r?.vertical_profile!=null));
            foreach(var road in roads.Where(r=>r?.vertical_profile!=null)) {
                if(!pending.Contains(road))continue;
                var component=new HashSet<GeoForgeRoad>{road};
                if(road.road_category=="automotive"&&!road.bridge&&!road.tunnel&&road.layer.HasValue) {
                    var nodes=new HashSet<string>(road.node_ids??new List<string>());bool changed;
                    do {changed=false;foreach(var other in pending)
                        if(!component.Contains(other)&&other.road_category=="automotive"&&!other.bridge&&!other.tunnel&&other.layer==road.layer&&
                            other.node_ids!=null&&other.node_ids.Any(n=>nodes.Contains(n))) {
                            component.Add(other);nodes.UnionWith(other.node_ids);changed=true;
                        }
                    }while(changed);
                }
                var sample=ConnectedHeight(road,component.ToArray(),settings,localSections);
                var cache=new Dictionary<(float,float),float>();
                Func<float,float,float> cached=(x,z)=>{if(cache.TryGetValue((x,z),out var h))return h;h=sample(x,z);if(cache.Count<1000000)cache[(x,z)]=h;return h;};
                foreach(var member in component){result.Add(member,cached);pending.Remove(member);}
            }
            return result;
        }

        public static Func<float,float,float> ConnectedHeight(GeoForgeRoad road,IList<GeoForgeRoad> roads,
            GeoForgeRoadGeometrySettings settings,bool localSections=false)
        {
            var own = new ProfileSampler(road.vertical_profile);
            if (road.road_category != "automotive" || road.bridge || road.tunnel || !road.layer.HasValue)
                return (x,z) => own.Sample(x,z,out _);
            // One canonical component, independent of which mesh requests a height.
            // Nodes define connectivity; XY proximity never merges grade separation.
            var eligible = roads.Where(r => r.vertical_profile != null && r.road_category == "automotive" &&
                !r.bridge && !r.tunnel && r.layer == road.layer).OrderBy(r => r.id,StringComparer.Ordinal).ToArray();
            var component = new HashSet<GeoForgeRoad>{road};
            var nodes = new HashSet<string>(road.node_ids ?? new List<string>());
            bool changed;
            do {
                changed = false;
                foreach(var other in eligible)
                    if(!component.Contains(other) && other.node_ids != null && other.node_ids.Any(n => nodes.Contains(n))) {
                        component.Add(other);nodes.UnionWith(other.node_ids);changed = true;
                    }
            } while(changed);
            var entries = component.OrderBy(r => r.id,StringComparer.Ordinal)
                .Select(r => (road:r, sampler:new ProfileSampler(r.vertical_profile,localSections?r.width/2:1,localSections))).ToArray();
            // Conservative spatial index of profile segments; radius exceeds ground
            // junction/transition extent. Same component and XY => same candidates.
            const float cell = 64;
            var buckets = new Dictionary<(int,int),HashSet<int>>();
            for(int k=0;k<entries.Length;k++) {
                var points=entries[k].road.vertical_profile.points;
                for(int i=1;i<points.Length;i++) {
                    int xmin=(int)Math.Floor((Math.Min(points[i-1][0],points[i][0])-cell)/cell);
                    int xmax=(int)Math.Floor((Math.Max(points[i-1][0],points[i][0])+cell)/cell);
                    int zmin=(int)Math.Floor((Math.Min(points[i-1][1],points[i][1])-cell)/cell);
                    int zmax=(int)Math.Floor((Math.Max(points[i-1][1],points[i][1])+cell)/cell);
                    for(int z=zmin;z<=zmax;z++)for(int x=xmin;x<=xmax;x++) {
                        if(!buckets.TryGetValue((x,z),out var indices)){indices=new HashSet<int>();buckets.Add((x,z),indices);}
                        indices.Add(k);
                    }
                }
            }
            var index=buckets.ToDictionary(pair=>pair.Key,pair=>pair.Value.OrderBy(k=>k).Select(k=>entries[k].sampler).ToArray());
            var all=entries.Select(e=>e.sampler).ToArray();
            return (x,z) => JunctionHeight(index.TryGetValue(((int)Math.Floor(x/cell),(int)Math.Floor(z/cell)),out var near)?near:all,x,z);
        }

        private static float JunctionHeight(ProfileSampler[] profiles,float x,float z)
        {
            double nearest=double.PositiveInfinity;float nearestHeight=0;
            foreach(var profile in profiles)
            {
                float height=profile.Sample(x,z,out double distance);distance/=profile.HalfWidthSquared;
                if(distance<nearest){nearest=distance;nearestHeight=height;}
            }
            // Exact centreline samples stay exact, including shared endpoints.
            if(nearest<1e-12)return nearestHeight;
            double weighted=0,total=0;
            foreach(var profile in profiles)
            {
                float height=profile.Sample(x,z,out double distance);distance/=profile.HalfWidthSquared;
                // Compact continuous weights: only curves within twice the
                // closest planar distance contribute. Far endpoint clamps cannot
                // flatten an adjoining road's width transition.
                // Width-normalized distance keeps the continuous component
                // field; no hard physical-ribbon cutoff and fallback jump.
                double weight=Math.Max(0,1-distance/(4*nearest));weight*=weight;
                weighted+=weight*height;total+=weight;
            }
            return total>0?(float)(weighted/total):nearestHeight;
        }
        /// <summary>Agree elevations at coincident mesh seams of connected ground
        /// automotive roads. Never move X/Z or join unrelated/layer-separated roads.</summary>
        public static int StitchSharedVertices(IDictionary<GeoForgeRoad,GeoForgeMeshData> meshes)
        {
            var groups=new Dictionary<(long,long,int),Dictionary<GeoForgeRoad,List<int>>>();
            foreach(var pair in meshes)
            {
                var road=pair.Key;if(road.road_category!="automotive"||road.bridge||road.tunnel||!road.layer.HasValue)continue;
                for(int i=0;i<pair.Value.Vertices.Count;i++)
                {
                    var p=pair.Value.Vertices[i];var key=((long)Math.Round(p.x*1000),(long)Math.Round(p.z*1000),road.layer.Value);
                    if(!groups.TryGetValue(key,out var owners)){owners=new Dictionary<GeoForgeRoad,List<int>>();groups.Add(key,owners);}
                    if(!owners.TryGetValue(road,out var indices)){indices=new List<int>();owners.Add(road,indices);}indices.Add(i);
                }
            }
            int stitched=0;
            foreach(var owners in groups.Values)
            {
                if(owners.Count<2)continue;
                var roads=owners.Keys.ToArray();
                bool connected=true;
                for(int i=1;i<roads.Length;i++)
                    if(roads[0].node_ids==null||roads[i].node_ids==null||!roads[0].node_ids.Intersect(roads[i].node_ids).Any())connected=false;
                if(!connected)continue;
                // A profile station is a constraint, not an arbitrary seam
                // vertex. Keep its height when adjacent patch vertices meet it.
                var anchors=owners.Where(owner=>owner.Key.vertical_profile!=null).SelectMany(owner=>
                    owner.Value.Where(i=>owner.Key.vertical_profile.points.Any(p=>PlanarDistance(
                        meshes[owner.Key].Vertices[i],new Vector3((float)p[0],0,(float)p[1]))<1e-10f))
                    .Take(1).Select(i=>meshes[owner.Key].Vertices[i].y)).ToArray();
                float height=anchors.Length>0?anchors.Average():owners.Average(owner=>meshes[owner.Key].Vertices[owner.Value[0]].y);
                foreach(var owner in owners)foreach(int i in owner.Value)
                {var p=meshes[owner.Key].Vertices[i];p.y=height;meshes[owner.Key].Vertices[i]=p;}
                stitched++;
            }
            return stitched;
        }
        public static void Validate(GeoForgeRoadVerticalProfile profile)
        {
            if(profile?.points==null||profile.points.Length<2)throw new ArgumentException("Road profile needs at least two points.");
            for(int i=0;i<profile.points.Length;i++)
            {
                var p=profile.points[i];
                if(p==null||p.Length!=3)throw new ArgumentException("Invalid profile point.");
                foreach(var v in p)if(!GeoForgeCoordinateConverter.IsFinite(v))throw new ArgumentException("Nonfinite profile point.");
                if(i>0)
                {
                    var a=profile.points[i-1];double dx=p[0]-a[0],dz=p[1]-a[1];
                    if(dx*dx+dz*dz<1e-16)throw new ArgumentException("Zero-length profile span.");
                }
            }
        }

        public static float Height(GeoForgeRoadVerticalProfile profile,float x,float z)
            =>new ProfileSampler(profile).Sample(x,z,out _);

        // Collinear stations belong to one geometric run. They still define its
        // vertical interpolation, but must not create artificial lateral ripples
        // by competing as separate clamped segments.
        private sealed class ProfileSampler
        {
            private sealed class Run
            {
                public double[][] points;
                public double dx,dz,lengthSquared;
                public double Distance(float x,float z,out double t)
                {
                    var a=points[0];
                    t=Math.Max(0,Math.Min(1,((x-a[0])*dx+(z-a[1])*dz)/lengthSquared));
                    double ex=x-a[0]-t*dx,ez=z-a[1]-t*dz;return ex*ex+ez*ez;
                }
                public double Height(double t)
                {
                    if(t<=0)return points[0][2];if(t>=1)return points[points.Length-1][2];
                    double previous=0;
                    for(int i=1;i<points.Length;i++)
                    {
                        double next=((points[i][0]-points[0][0])*dx+(points[i][1]-points[0][1])*dz)/lengthSquared;
                        if(t<=next)return points[i-1][2]+(points[i][2]-points[i-1][2])*(t-previous)/(next-previous);
                        previous=next;
                    }
                    return points[points.Length-1][2];
                }
            }
            private readonly List<Run> runs=new List<Run>();
            public readonly double HalfWidthSquared;
            private readonly GeoForgeRoadFrame frame;
            public ProfileSampler(GeoForgeRoadVerticalProfile profile,double halfWidth=1,bool useFrame=false)
            {
                HalfWidthSquared=Math.Max(0.01,halfWidth*halfWidth);
                frame=useFrame?new GeoForgeRoadFrame(profile,halfWidth):null;
                var points=profile.points;int start=0;
                for(int i=1;i<points.Length;i++)
                {
                    bool end=i==points.Length-1;
                    if(!end)
                    {
                        double ax=points[i][0]-points[start][0],az=points[i][1]-points[start][1];
                        double bx=points[i+1][0]-points[i][0],bz=points[i+1][1]-points[i][1];
                        double cross=ax*bz-az*bx;
                        end=ax*bx+az*bz<=0||cross*cross>1e-16*(ax*ax+az*az)*(bx*bx+bz*bz);
                    }
                    if(!end)continue;
                    double dx=points[i][0]-points[start][0],dz=points[i][1]-points[start][1];
                    runs.Add(new Run{points=points.Skip(start).Take(i-start+1).ToArray(),dx=dx,dz=dz,lengthSquared=dx*dx+dz*dz});
                    start=i;
                }
            }
            public float Sample(float x,float z,out double closest)
            {
                closest=double.PositiveInfinity;double nearestHeight=0;
                foreach(var run in runs)
                {
                    double distance=run.Distance(x,z,out double t);
                    if(distance<closest){closest=distance;nearestHeight=run.Height(t);}
                }
                if(closest<1e-12)return (float)nearestHeight;
                if(frame!=null&&frame.TryHeight(x,z,out float framed))return framed;
                if(runs.Count==1)return (float)nearestHeight;
                double weighted=0,total=0;
                foreach(var run in runs)
                {
                    double distance=run.Distance(x,z,out double t);
                    double weight=Math.Max(0,1-distance/(4*closest));weight*=weight;
                    if(weight==0)continue;
                    weighted+=weight*run.Height(t);total+=weight;
                }
                return (float)(weighted/total);
            }
        }

        /// <summary>Preserve planar mesh and its style offset; replace raw DSM drape
        /// with the exported profile. Bounded subdivision samples long spans.</summary>
        public static GeoForgeMeshData Build(GeoForgeMeshData source,GeoForgeRoadVerticalProfile profile,
            float maximumEdgeMeters=5,int maximumTriangles=100000,Func<float,float,float> heightSampler=null,
            float maximumHeightErrorMeters=0.01f,float minimumAdaptiveEdgeMeters=0.25f,bool preserveProfileAnchors=true)
        {
            Validate(profile);
            if(!GeoForgeCoordinateConverter.IsFinite(maximumEdgeMeters)||maximumEdgeMeters<=0||maximumTriangles<1||
                !GeoForgeCoordinateConverter.IsFinite(maximumHeightErrorMeters)||maximumHeightErrorMeters<=0||
                !GeoForgeCoordinateConverter.IsFinite(minimumAdaptiveEdgeMeters)||minimumAdaptiveEdgeMeters<=0)
                throw new ArgumentException("Invalid profile surface budget.");
            var result=new GeoForgeMeshData();
            if(!profile.surface_visible)return result;
            int reserved=source.Triangles.Count/3;
            if(reserved>maximumTriangles)throw new ArgumentException("Profile input exceeds triangle budget.");
            float limit=maximumEdgeMeters*maximumEdgeMeters;
            float minimum=minimumAdaptiveEdgeMeters*minimumAdaptiveEdgeMeters;
            var stations=new Dictionary<(float,float),float>();
            foreach(var p in profile.points)stations[((float)p[0],(float)p[1])]=(float)p[2];
            var profileSampler=new ProfileSampler(profile);
            Func<Vector3,float> sample=p=>preserveProfileAnchors&&stations.TryGetValue((p.x,p.z),out float station)?station:
                heightSampler==null?profileSampler.Sample(p.x,p.z,out _):heightSampler(p.x,p.z);
            Action<Vector3,Vector3,Vector3,int,bool,int> emit=null;
            emit=(a,b,c,depth,refinementAllowed,nextStation)=>
            {
                float ab=PlanarDistance(a,b),bc=PlanarDistance(b,c),ca=PlanarDistance(c,a);
                float longest=Mathf.Max(ab,Mathf.Max(bc,ca));
                float ha=sample(a),hb=sample(b),hc=sample(c);
                // Longest-edge subdivision alone can bridge a profile crest even
                // when all edges are shorter than the sampling spacing. Check the
                // interpolated surface too. The minimum edge bounds refinement at
                // discontinuities between nearest connected profile regions; this
                // is a sampling tolerance, not a global error guarantee.
                bool refine=longest>limit;
                if(!refine&&longest>minimum)
                    refine=Math.Abs(sample((a+b)/2)-(ha+hb)/2)>maximumHeightErrorMeters||
                        Math.Abs(sample((b+c)/2)-(hb+hc)/2)>maximumHeightErrorMeters||
                        Math.Abs(sample((c+a)/2)-(hc+ha)/2)>maximumHeightErrorMeters||
                        Math.Abs(sample((a+b+c)/3)-(ha+hb+hc)/3)>maximumHeightErrorMeters||
                        Math.Abs(sample((3*a+b)/4)-(3*ha+hb)/4)>maximumHeightErrorMeters||
                        Math.Abs(sample((a+3*b)/4)-(ha+3*hb)/4)>maximumHeightErrorMeters||
                        Math.Abs(sample((3*b+c)/4)-(3*hb+hc)/4)>maximumHeightErrorMeters||
                        Math.Abs(sample((b+3*c)/4)-(hb+3*hc)/4)>maximumHeightErrorMeters||
                        Math.Abs(sample((3*c+a)/4)-(3*hc+ha)/4)>maximumHeightErrorMeters||
                        Math.Abs(sample((c+3*a)/4)-(hc+3*ha)/4)>maximumHeightErrorMeters||
                        Math.Abs(sample((2*a+b+c)/4)-(2*ha+hb+hc)/4)>maximumHeightErrorMeters||
                        Math.Abs(sample((a+2*b+c)/4)-(ha+2*hb+hc)/4)>maximumHeightErrorMeters||
                        Math.Abs(sample((a+b+2*c)/4)-(ha+hb+2*hc)/4)>maximumHeightErrorMeters;
                if(refine&&refinementAllowed)
                {
                    if(depth>=32||reserved>=maximumTriangles)throw new ArgumentException("Profile surface subdivision budget exceeded.");
                    reserved++;
                    if(ab>=bc&&ab>=ca){var m=(a+b)/2;emit(a,m,c,depth+1,true,0);emit(m,b,c,depth+1,true,0);}
                    else if(bc>=ca){var m=(b+c)/2;emit(a,b,m,depth+1,true,0);emit(a,m,c,depth+1,true,0);}
                    else {var m=(c+a)/2;emit(a,b,m,depth+1,true,0);emit(m,b,c,depth+1,true,0);}
                    return;
                }
                // Preserve the conditioned centerline stations in the actual
                // triangle surface. A centimetre of interpolation error can still
                // break grade/curvature constraints on short source intervals.
                for(int stationIndex=nextStation;stationIndex<profile.points.Length;stationIndex++)
                {
                    var station=profile.points[stationIndex];
                    var p=new Vector3((float)station[0],0,(float)station[1]);
                    if(PlanarDistance(p,a)<1e-10f||PlanarDistance(p,b)<1e-10f||PlanarDistance(p,c)<1e-10f)continue;
                    if(!Weights(a,b,c,p,out double u,out double v))continue;
                    if(depth>=32||reserved+2>maximumTriangles)throw new ArgumentException("Profile anchor subdivision budget exceeded.");
                    p.y=(float)(u*a.y+v*b.y+(1-u-v)*c.y);reserved+=2;
                    // Insert anchors after adaptive refinement. Refining their
                    // tiny incident faces again can repeatedly reinsert the same
                    // near-edge station and exhaust the recursion budget.
                    if(!Sliver(a,b,p))emit(a,b,p,depth+1,false,stationIndex+1);
                    if(!Sliver(b,c,p))emit(b,c,p,depth+1,false,stationIndex+1);
                    if(!Sliver(c,a,p))emit(c,a,p,depth+1,false,stationIndex+1);
                    return;
                }
                int k=result.Vertices.Count;
                result.Vertices.Add(a+Vector3.up*ha);
                result.Vertices.Add(b+Vector3.up*hb);
                result.Vertices.Add(c+Vector3.up*hc);
                result.AddUpTriangle(k,k+1,k+2);
            };
            for(int i=0;i<source.Triangles.Count;i+=3)
                emit(source.Vertices[source.Triangles[i]],source.Vertices[source.Triangles[i+1]],source.Vertices[source.Triangles[i+2]],0,true,0);
            return GeoForgeRoadMeshSeams.Conform(result,maximumTriangles);
        }
        private static float PlanarDistance(Vector3 a,Vector3 b)
            =>(a.x-b.x)*(a.x-b.x)+(a.z-b.z)*(a.z-b.z);
        private static double PlanarArea(Vector3 a,Vector3 b,Vector3 c)
            =>Math.Abs(((double)b.x-a.x)*((double)c.z-a.z)-((double)b.z-a.z)*((double)c.x-a.x));
        private static bool Sliver(Vector3 a,Vector3 b,Vector3 c)
            =>PlanarArea(a,b,c)<=0.0001*Math.Sqrt(Math.Max(PlanarDistance(a,b),Math.Max(PlanarDistance(b,c),PlanarDistance(c,a))));
        private static bool Weights(Vector3 a,Vector3 b,Vector3 c,Vector3 p,out double u,out double v)
        {
            u=v=0;
            // Offset half-planes of a very acute triangle can meet far beyond
            // its tips. Bound the tolerance spatially as well as barycentrically.
            if(p.x<Math.Min(a.x,Math.Min(b.x,c.x))-0.0001||p.x>Math.Max(a.x,Math.Max(b.x,c.x))+0.0001||
                p.z<Math.Min(a.z,Math.Min(b.z,c.z))-0.0001||p.z>Math.Max(a.z,Math.Max(b.z,c.z))+0.0001)return false;
            double determinant=((double)b.z-c.z)*((double)a.x-c.x)+((double)c.x-b.x)*((double)a.z-c.z);
            u=v=0;if(Math.Abs(determinant)<1e-12)return false;
            u=(((double)b.z-c.z)*((double)p.x-c.x)+((double)c.x-b.x)*((double)p.z-c.z))/determinant;
            v=(((double)c.z-a.z)*((double)p.x-c.x)+((double)a.x-c.x)*((double)p.z-c.z))/determinant;
            // Float midpoints on a shared edge can differ from the source line
            // by micrometres. PhysX accepts hits just outside such edges. Insert
            // the station into both incident faces within the same 0.1 mm
            // geometric tolerance used for derived cutout fragments.
            double scale=0.0001/Math.Abs(determinant);
            return u>=-scale*Math.Sqrt(PlanarDistance(b,c))&&
                v>=-scale*Math.Sqrt(PlanarDistance(c,a))&&
                1-u-v>=-scale*Math.Sqrt(PlanarDistance(a,b));
        }
    }
}
