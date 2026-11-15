using System;
using System.Collections.Generic;
using UnityEngine;

namespace GeoForge
{
    [Serializable]
    public sealed class GeoForgeRoadbedSettings
    {
        public bool enabled=false;
        public float shoulderMeters=4;
        public float crossingShoulderMeters=0.3f;
        public float surfaceSeparationMeters=0.03f;
        public float approximationMeters=0.005f;
        public float minimumEdgeMeters=0.15f;
        public int maximumTriangles=2000000;
    }

    /// <summary>Derived roadbed only. Never changes the source terrain grid.
    /// Ground automotive ribbons get shoulders; explicit ground crossings get
    /// a small local correction. Bridges/tunnels/nonzero layers are excluded.</summary>
    public sealed class GeoForgeRoadbed
    {
        private readonly GeoForgeRoadbedSettings settings;
        private const float Cell=4;
        private readonly List<(Vector3 a,Vector3 b,Vector3 c)> faces=new List<(Vector3,Vector3,Vector3)>();
        private readonly List<(Vector3 a,Vector3 b,float radius)> edges=new List<(Vector3,Vector3,float)>();
        private readonly Dictionary<(int,int),List<int>> faceBins=new Dictionary<(int,int),List<int>>();
        private readonly Dictionary<(int,int),List<int>> edgeBins=new Dictionary<(int,int),List<int>>();
        private readonly List<GeoForgeMeshData> floors=new List<GeoForgeMeshData>();
        public int EligibleRoads {get;private set;}
        public static bool Applies(GeoForgeRoad r) => r!=null&&!r.bridge&&!r.tunnel&&r.layer==0&&
            (r.road_category=="automotive"||GeoForgeCrossingElevation.Applies(r));

        public GeoForgeRoadbed(IDictionary<GeoForgeRoad,GeoForgeMeshData> roads,GeoForgeRoadbedSettings settings)
        {
            this.settings=settings;
            if(settings.shoulderMeters<=0||settings.crossingShoulderMeters<=0||settings.surfaceSeparationMeters<=0||
               settings.approximationMeters<=0||settings.minimumEdgeMeters<=0||settings.maximumTriangles<1)
                throw new ArgumentException("Invalid roadbed settings.");
            foreach(var item in roads) {
                if(!Applies(item.Key))continue;
                EligibleRoads++;floors.Add(item.Value);
                float radius=item.Key.road_category=="automotive"?settings.shoulderMeters:settings.crossingShoulderMeters;
                var boundary=new Dictionary<((long,long),(long,long)),(int count,Vector3 a,Vector3 b)>();
                var m=item.Value;
                for(int i=0;i<m.Triangles.Count;i+=3) {
                    var a=m.Vertices[m.Triangles[i]];var b=m.Vertices[m.Triangles[i+1]];var c=m.Vertices[m.Triangles[i+2]];
                    if(Math.Abs(Side(a,b,c.x,c.z))<1e-10)continue;
                    int id=faces.Count;faces.Add((a,b,c));
                    Index(faceBins,id,Math.Min(a.x,Math.Min(b.x,c.x)),Math.Max(a.x,Math.Max(b.x,c.x)),
                        Math.Min(a.z,Math.Min(b.z,c.z)),Math.Max(a.z,Math.Max(b.z,c.z)));
                    void Edge(Vector3 u,Vector3 v) {
                        var uk=((long)Math.Round(u.x*10000),(long)Math.Round(u.z*10000));
                        var vk=((long)Math.Round(v.x*10000),(long)Math.Round(v.z*10000));
                        var key=uk.CompareTo(vk)<0?(uk,vk):(vk,uk);
                        if(boundary.TryGetValue(key,out var prior))boundary[key]=(prior.count+1,prior.a,prior.b);
                        else boundary.Add(key,(1,u,v));
                    }
                    Edge(a,b);Edge(b,c);Edge(c,a);
                }
                foreach(var edge in boundary.Values)if(edge.count==1) {
                    int id=edges.Count;edges.Add((edge.a,edge.b,radius));
                    Index(edgeBins,id,Math.Min(edge.a.x,edge.b.x)-radius,Math.Max(edge.a.x,edge.b.x)+radius,
                        Math.Min(edge.a.z,edge.b.z)-radius,Math.Max(edge.a.z,edge.b.z)+radius);
                }
            }
        }
        private static void Index(Dictionary<(int,int),List<int>> bins,int id,float xmin,float xmax,float zmin,float zmax)
        {
            for(int z=(int)Math.Floor(zmin/Cell);z<=(int)Math.Floor(zmax/Cell);z++)
            for(int x=(int)Math.Floor(xmin/Cell);x<=(int)Math.Floor(xmax/Cell);x++) {
                if(!bins.TryGetValue((x,z),out var ids)){ids=new List<int>();bins.Add((x,z),ids);}ids.Add(id);
            }
        }
        private static double Side(Vector3 a,Vector3 b,double x,double z)
            =>((double)b.x-a.x)*(z-a.z)-((double)b.z-a.z)*(x-a.x);

        public float Height(float x,float z,float original,out bool influenced)
        {
            var cell=((int)Math.Floor(x/Cell),(int)Math.Floor(z/Cell));
            double level=double.PositiveInfinity;
            if(faceBins.TryGetValue(cell,out var fs))foreach(int id in fs) {
                var t=faces[id];double det=Side(t.a,t.b,t.c.x,t.c.z);
                double u=Side(t.b,t.c,x,z)/det,v=Side(t.c,t.a,x,z)/det,w=1-u-v;
                if(u>=-1e-7&&v>=-1e-7&&w>=-1e-7)level=Math.Min(level,u*t.a.y+v*t.b.y+w*t.c.y);
            }
            if(!double.IsPositiveInfinity(level)) {influenced=true;return (float)level-settings.surfaceSeparationMeters;}
            double nearest=double.PositiveInfinity,selected=0,radius=0;
            if(edgeBins.TryGetValue(cell,out var es))foreach(int id in es) {
                var e=edges[id];double dx=e.b.x-e.a.x,dz=e.b.z-e.a.z,ls=dx*dx+dz*dz;
                double t=ls<1e-14?0:Math.Max(0,Math.Min(1,((x-e.a.x)*dx+(z-e.a.z)*dz)/ls));
                double ex=x-e.a.x-t*dx,ez=z-e.a.z-t*dz,d=Math.Sqrt(ex*ex+ez*ez);
                if(d>=e.radius||d>=nearest)continue;
                nearest=d;selected=e.a.y+t*(e.b.y-e.a.y);radius=e.radius;
            }
            influenced=!double.IsPositiveInfinity(nearest);
            if(!influenced)return original;
            double blend=1-nearest/radius;blend=blend*blend*(3-2*blend);
            return (float)(original*(1-blend)+(selected-settings.surfaceSeparationMeters)*blend);
        }
        public GeoForgeMeshData Condition(GeoForgeMeshData source)
        {
            if(EligibleRoads==0)return source;
            var result=new GeoForgeMeshData();int reserved=source.Triangles.Count/3;
            void Emit(Vector3 a,Vector3 b,Vector3 c,int depth) {
                float ha=Height(a.x,a.z,a.y,out bool ia),hb=Height(b.x,b.z,b.y,out bool ib),hc=Height(c.x,c.z,c.y,out bool ic);
                Vector3 ab=(a+b)/2,bc=(b+c)/2,ca=(c+a)/2,mid=(a+b+c)/3;
                float hab=Height(ab.x,ab.z,ab.y,out bool iab),hbc=Height(bc.x,bc.z,bc.y,out bool ibc),hca=Height(ca.x,ca.z,ca.y,out bool ica);
                float hm=Height(mid.x,mid.z,mid.y,out bool im);
                float dab=Distance(a,b),dbc=Distance(b,c),dca=Distance(c,a),longest=Math.Max(dab,Math.Max(dbc,dca));
                bool touched=ia||ib||ic||iab||ibc||ica||im;
                bool error=Math.Abs(hab-(ha+hb)/2)>settings.approximationMeters||Math.Abs(hbc-(hb+hc)/2)>settings.approximationMeters||
                    Math.Abs(hca-(hc+ha)/2)>settings.approximationMeters||Math.Abs(hm-(ha+hb+hc)/3)>settings.approximationMeters;
                if(touched&&longest>settings.minimumEdgeMeters*settings.minimumEdgeMeters&&(error||longest>4)) {
                    if(depth>=32||++reserved>settings.maximumTriangles)throw new ArgumentException("Roadbed subdivision budget exceeded.");
                    if(dab>=dbc&&dab>=dca){Emit(a,ab,c,depth+1);Emit(ab,b,c,depth+1);}
                    else if(dbc>=dca){Emit(a,b,bc,depth+1);Emit(a,bc,c,depth+1);}
                    else {Emit(a,b,ca,depth+1);Emit(ca,b,c,depth+1);}
                    return;
                }
                a.y=ha;b.y=hb;c.y=hc;int k=result.Vertices.Count;
                result.Vertices.Add(a);result.Vertices.Add(b);result.Vertices.Add(c);result.AddUpTriangle(k,k+1,k+2);
            }
            for(int i=0;i<source.Triangles.Count;i+=3)Emit(source.Vertices[source.Triangles[i]],source.Vertices[source.Triangles[i+1]],source.Vertices[source.Triangles[i+2]],0);
            return GeoForgeRoadMeshSeams.Conform(result,settings.maximumTriangles);
        }
        private static float Distance(Vector3 a,Vector3 b)=>(a.x-b.x)*(a.x-b.x)+(a.z-b.z)*(a.z-b.z);
        public GeoForgeMeshData WithFloors(GeoForgeMeshData land)
        {
            var result=new GeoForgeMeshData();result.Vertices.AddRange(land.Vertices);result.Triangles.AddRange(land.Triangles);
            foreach(var floor in floors) {
                int k=result.Vertices.Count;
                foreach(var p in floor.Vertices)result.Vertices.Add(p-Vector3.up*settings.surfaceSeparationMeters);
                foreach(int i in floor.Triangles)result.Triangles.Add(k+i);
            }
            return result;
        }
    }
}
