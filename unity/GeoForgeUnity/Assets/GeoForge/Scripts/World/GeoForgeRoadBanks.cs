using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace GeoForge
{
    /// <summary>Vertical derived caps between clipped land and the actual road mesh.
    /// These are reconstruction geometry, not surveyed retaining walls or slopes.</summary>
    public static class GeoForgeRoadBanks
    {
        private const double Tolerance = 0.0002;
        private const float Cell = 32;

        public sealed class Result
        {
            public readonly GeoForgeMeshData Mesh = new GeoForgeMeshData();
            public int BoundaryEdges, Segments;
            public int SurfaceTrianglesScanned, SurfaceTrianglesIndexed;
            public int InputCapIntervals, MergedCapIntervals;
            public double SimplificationToleranceMeters, MaximumSimplificationErrorMeters;
            public double MissingRoadSurfaceMeters, MaximumHeightDifferenceMeters;
            public double ExcludedNonRoadEdgeMeters;
            public readonly List<double[]> MissingRoadSurfaceExamples=new List<double[]>();
        }

        private sealed class Triangle
        {
            public Vector3 A, B, C;
            public double Determinant;
            public float MinX, MaxX, MinZ, MaxZ;
            public Triangle(Vector3 a, Vector3 b, Vector3 c)
            {
                A=a; B=b; C=c;
                Determinant=((double)b.z-c.z)*((double)a.x-c.x)+((double)c.x-b.x)*((double)a.z-c.z);
                MinX=Math.Min(a.x,Math.Min(b.x,c.x)); MaxX=Math.Max(a.x,Math.Max(b.x,c.x));
                MinZ=Math.Min(a.z,Math.Min(b.z,c.z)); MaxZ=Math.Max(a.z,Math.Max(b.z,c.z));
            }
            public void Weights(double x,double z,out double u,out double v)
            {
                u=(((double)B.z-C.z)*(x-C.x)+((double)C.x-B.x)*(z-C.z))/Determinant;
                v=(((double)C.z-A.z)*(x-C.x)+((double)A.x-C.x)*(z-C.z))/Determinant;
            }
            public double Height(double x,double z)
            {
                Weights(x,z,out double u,out double v);
                // A cut edge may lie microscopically outside the road triangle.
                // Clamp barycentric weights there instead of extrapolating a
                // nearly vertical narrow face into an artificial height spike.
                double w=Math.Max(0,1-u-v);u=Math.Max(0,u);v=Math.Max(0,v);
                return (u*A.y+v*B.y+w*C.y)/(u+v+w);
            }
            public bool Contains(double x,double z)
            {
                if(x<MinX-Tolerance||x>MaxX+Tolerance||z<MinZ-Tolerance||z>MaxZ+Tolerance)return false;
                Weights(x,z,out double u,out double v);
                double k=Tolerance/Math.Abs(Determinant);
                return u>=-k*Distance(B,C)&&v>=-k*Distance(C,A)&&1-u-v>=-k*Distance(A,B);
            }
            public double DistanceTo(double x,double z)
            {
                Weights(x,z,out double u,out double v);
                if(u>=0&&v>=0&&u+v<=1)return 0;
                return Math.Min(SegmentDistance(A,B,x,z),Math.Min(SegmentDistance(B,C,x,z),SegmentDistance(C,A,x,z)));
            }
            private static double SegmentDistance(Vector3 a,Vector3 b,double x,double z)
            {
                double dx=(double)b.x-a.x,dz=(double)b.z-a.z,square=dx*dx+dz*dz;
                double t=square<1e-20?0:Math.Max(0,Math.Min(1,((x-a.x)*dx+(z-a.z)*dz)/square));
                double ex=x-a.x-t*dx,ez=z-a.z-t*dz;
                return Math.Sqrt(ex*ex+ez*ez);
            }
            public bool Clip(Vector3 a,Vector3 b,out double lo,out double hi)
            {
                lo=0; hi=1;
                Weights(a.x,a.z,out double u0,out double v0);
                Weights(b.x,b.z,out double u1,out double v1);
                double k=Tolerance/Math.Abs(Determinant);
                return Bound(u0,u1,-k*Distance(B,C),ref lo,ref hi)&&
                    Bound(v0,v1,-k*Distance(C,A),ref lo,ref hi)&&
                    Bound(1-u0-v0,1-u1-v1,-k*Distance(A,B),ref lo,ref hi)&&
                    Bound(a.x,b.x,MinX-Tolerance,ref lo,ref hi)&&
                    Bound(-a.x,-b.x,-MaxX-Tolerance,ref lo,ref hi)&&
                    Bound(a.z,b.z,MinZ-Tolerance,ref lo,ref hi)&&
                    Bound(-a.z,-b.z,-MaxZ-Tolerance,ref lo,ref hi);
            }
            private static bool Bound(double a,double b,double minimum,ref double lo,ref double hi)
            {
                double delta=b-a;
                if(Math.Abs(delta)<1e-15)return a>=minimum;
                double t=(minimum-a)/delta;
                if(delta>0)lo=Math.Max(lo,t); else hi=Math.Min(hi,t);
                return hi>lo;
            }
        }

        private sealed class Index
        {
            private readonly Dictionary<(int,int),List<Triangle>> cells=new Dictionary<(int,int),List<Triangle>>();
            public int Scanned, Indexed;
            public Index(IEnumerable<GeoForgeMeshData> meshes,Func<Triangle,bool> relevant=null)
            {
                int count=0,entries=0;
                foreach(var mesh in meshes)
                {
                    if(mesh==null||mesh.Triangles.Count%3!=0)throw new ArgumentException("Invalid bank input mesh.");
                    for(int i=0;i<mesh.Triangles.Count;i+=3)
                    {
                        if(++Scanned>10000000)throw new ArgumentException("Road bank scan budget exceeded.");
                        var t=new Triangle(mesh.Vertices[mesh.Triangles[i]],mesh.Vertices[mesh.Triangles[i+1]],mesh.Vertices[mesh.Triangles[i+2]]);
                        foreach(var p in new[]{t.A,t.B,t.C})
                            if(!GeoForgeCoordinateConverter.IsFinite(p.x)||!GeoForgeCoordinateConverter.IsFinite(p.y)||!GeoForgeCoordinateConverter.IsFinite(p.z))
                                throw new ArgumentException("Nonfinite road bank input.");
                        if(Math.Abs(t.Determinant)<1e-10)continue;
                        if(relevant!=null&&!relevant(t))continue;
                        if(++count>1000000)throw new ArgumentException("Road bank indexed triangle budget exceeded.");
                        Indexed++;
                        for(int z=Bucket(t.MinZ-Tolerance);z<=Bucket(t.MaxZ+Tolerance);z++)
                        for(int x=Bucket(t.MinX-Tolerance);x<=Bucket(t.MaxX+Tolerance);x++)
                        {
                            if(++entries>2000000)throw new ArgumentException("Road bank spatial index budget exceeded.");
                            if(!cells.TryGetValue((x,z),out var list)){list=new List<Triangle>();cells.Add((x,z),list);}
                            list.Add(t);
                        }
                    }
                }
            }
            public bool Contains(double x,double z)
                =>cells.TryGetValue((Bucket(x),Bucket(z)),out var list)&&list.Any(t=>t.Contains(x,z));
            public IEnumerable<Triangle> Query(Vector3 a,Vector3 b)
            {
                var found=new HashSet<Triangle>();
                for(int z=Bucket(Math.Min(a.z,b.z)-Tolerance);z<=Bucket(Math.Max(a.z,b.z)+Tolerance);z++)
                for(int x=Bucket(Math.Min(a.x,b.x)-Tolerance);x<=Bucket(Math.Max(a.x,b.x)+Tolerance);x++)
                    if(cells.TryGetValue((x,z),out var list))foreach(var t in list)
                        if(t.MaxX+Tolerance>=Math.Min(a.x,b.x)&&t.MinX-Tolerance<=Math.Max(a.x,b.x)&&
                            t.MaxZ+Tolerance>=Math.Min(a.z,b.z)&&t.MinZ-Tolerance<=Math.Max(a.z,b.z))found.Add(t);
                return found;
            }
            private static int Bucket(double value)=>(int)Math.Floor(value/Cell);
        }

        public static Result Build(GeoForgeMeshData clippedLand,IEnumerable<GeoForgeMeshData> flatRoadMasks,
            IEnumerable<GeoForgeMeshData> roadSurfaces,int maximumTriangles=1000000,double maximumHeightErrorMeters=0.0001)
        {
            if(clippedLand==null||flatRoadMasks==null||roadSurfaces==null||maximumTriangles<1||
                clippedLand.Triangles.Count%3!=0||clippedLand.Triangles.Count>3000000||
                double.IsNaN(maximumHeightErrorMeters)||double.IsInfinity(maximumHeightErrorMeters)||maximumHeightErrorMeters<0)
                throw new ArgumentException("Invalid road bank input or budget.");
            var result=new Result{SimplificationToleranceMeters=maximumHeightErrorMeters};var masks=new Index(flatRoadMasks);
            var edges=new Dictionary<(long,long,long,long),(Vector3 a,Vector3 b,int count)>();
            for(int i=0;i<clippedLand.Triangles.Count;i+=3)for(int edge=0;edge<3;edge++)
            {
                var a=clippedLand.Vertices[clippedLand.Triangles[i+edge]];
                var b=clippedLand.Vertices[clippedLand.Triangles[i+(edge+1)%3]];
                if(a.x>b.x||(a.x==b.x&&a.z>b.z)){var swap=a;a=b;b=swap;}
                double length=Distance(a,b);if(length<0.0001)continue;
                var key=((long)Math.Round(a.x*10000d),(long)Math.Round(a.z*10000d),(long)Math.Round(b.x*10000d),(long)Math.Round(b.z*10000d));
                if(edges.TryGetValue(key,out var value))edges[key]=(value.a,value.b,value.count+1);
                else edges.Add(key,(a,b,1));
            }
            // The surface index serves boundary queries only. Interior road
            // faces outside every possible query AABB cannot affect any cap.
            // Include the 5 cm diagnostic neighbourhood and numerical tolerance.
            const double queryPadding=0.051, queryCell=4;
            var boundaryQueries=new Dictionary<(int,int),List<(double minX,double maxX,double minZ,double maxZ)>>();
            foreach(var edge in edges.Values.Where(e=>e.count==1)) {
                var box=(minX:Math.Min(edge.a.x,edge.b.x)-queryPadding,maxX:Math.Max(edge.a.x,edge.b.x)+queryPadding,
                    minZ:Math.Min(edge.a.z,edge.b.z)-queryPadding,maxZ:Math.Max(edge.a.z,edge.b.z)+queryPadding);
                for(int z=(int)Math.Floor(box.minZ/queryCell);z<=(int)Math.Floor(box.maxZ/queryCell);z++)
                for(int x=(int)Math.Floor(box.minX/queryCell);x<=(int)Math.Floor(box.maxX/queryCell);x++) {
                    if(!boundaryQueries.TryGetValue((x,z),out var list)){list=new List<(double,double,double,double)>();boundaryQueries.Add((x,z),list);}
                    list.Add(box);
                }
            }
            bool Relevant(Triangle t) {
                for(int z=(int)Math.Floor(t.MinZ/queryCell);z<=(int)Math.Floor(t.MaxZ/queryCell);z++)
                for(int x=(int)Math.Floor(t.MinX/queryCell);x<=(int)Math.Floor(t.MaxX/queryCell);x++)
                    if(boundaryQueries.TryGetValue((x,z),out var list))foreach(var box in list)
                        if(t.MaxX>=box.minX&&t.MinX<=box.maxX&&t.MaxZ>=box.minZ&&t.MinZ<=box.maxZ)return true;
                return false;
            }
            var surfaces=new Index(roadSurfaces,Relevant);
            result.SurfaceTrianglesScanned=surfaces.Scanned;result.SurfaceTrianglesIndexed=surfaces.Indexed;
            foreach(var edge in edges.Values)
            {
                // A shared land edge is an internal triangulation edge, even
                // when its midpoint is extremely close to a road boundary.
                if(edge.count!=1)continue;
                var a=edge.a;var b=edge.b;double length=Distance(a,b);
                double x=((double)a.x+b.x)/2,z=((double)a.z+b.z)/2;
                double nx=(b.z-a.z)/length*0.005,nz=-(b.x-a.x)/length*0.005;
                // Only edges between land and the union of road masks. Internal
                // triangle edges and overlaps at junctions must not become walls.
                if(!masks.Contains(x,z)||masks.Contains(x+nx,z+nz)==masks.Contains(x-nx,z-nz))continue;
                result.BoundaryEdges++;
                var spans=new List<(Triangle triangle,double lo,double hi)>();
                var cuts=new SortedSet<double>{0,1};
                foreach(var triangle in masks.Query(a,b))
                    if(triangle.Clip(a,b,out double lo,out double hi)){cuts.Add(lo);cuts.Add(hi);}
                foreach(var triangle in surfaces.Query(a,b))
                    if(triangle.Clip(a,b,out double lo,out double hi))
                    {spans.Add((triangle,lo,hi));cuts.Add(lo);cuts.Add(hi);}
                if(spans.Count>2000)throw new ArgumentException("Road bank overlapping surface budget exceeded.");
                var stations=cuts.ToArray();
                var caps=new List<(double start,double end,double hp,double hq)>();
                for(int j=1;j<stations.Length;j++)
                {
                    double lo=stations[j-1],hi=stations[j];if((hi-lo)*length<0.0001)continue;
                    double mid=(lo+hi)/2;
                    double mx=a.x+((double)b.x-a.x)*mid,mz=a.z+((double)b.z-a.z)*mid;
                    // Nonconforming land edges may touch a road only along part
                    // of their length. Classify each clipped interval, not just
                    // the midpoint of the original candidate edge.
                    if(!masks.Contains(mx,mz)||masks.Contains(mx+nx,mz+nz)==masks.Contains(mx-nx,mz-nz))
                    {result.ExcludedNonRoadEdgeMeters+=(hi-lo)*length;continue;}
                    var active=spans.Where(s=>s.lo<=mid&&s.hi>=mid).Select(s=>s.triangle).ToArray();
                    if(active.Length==0)
                    {
                        result.MissingRoadSurfaceMeters+=(hi-lo)*length;
                        double nearest=surfaces.Query(new Vector3((float)mx-0.05f,0,(float)mz-0.05f),new Vector3((float)mx+0.05f,0,(float)mz+0.05f))
                            .Select(t=>t.DistanceTo(mx,mz)).DefaultIfEmpty(-1).Min();
                        if(result.MissingRoadSurfaceExamples.Count<20)result.MissingRoadSurfaceExamples.Add(new[]{
                            a.x+((double)b.x-a.x)*lo,a.z+((double)b.z-a.z)*lo,
                            a.x+((double)b.x-a.x)*hi,a.z+((double)b.z-a.z)*hi,nearest,masks.Contains(mx,mz)?1d:0d});
                        continue;
                    }
                    var envelope=new SortedSet<double>{lo,hi};
                    // Split where overlapping surface planes exchange which is
                    // uppermost, as well as at their triangle boundaries.
                    for(int u=0;u<active.Length;u++)for(int v=u+1;v<active.Length;v++)
                    {
                        double d0=Height(active[u],a,b,lo)-Height(active[v],a,b,lo);
                        double d1=Height(active[u],a,b,hi)-Height(active[v],a,b,hi);
                        if(d0*d1<0&&Math.Max(Math.Abs(d0),Math.Abs(d1))>1e-6)envelope.Add(lo+(hi-lo)*d0/(d0-d1));
                    }
                    var parts=envelope.ToArray();
                    for(int k=1;k<parts.Length;k++)
                    {
                        double start=parts[k-1],end=parts[k];if((end-start)*length<0.0001)continue;
                        var top=active.OrderByDescending(t=>Height(t,a,b,(start+end)/2)).First();
                        caps.Add((start,end,Height(top,a,b,start),Height(top,a,b,end)));
                    }
                }
                EmitCaps(result,a,b,caps,maximumTriangles,maximumHeightErrorMeters);
            }
            return result;
        }

        private static double Height(Triangle t,Vector3 a,Vector3 b,double f)
            =>t.Height(a.x+((double)b.x-a.x)*f,a.z+((double)b.z-a.z)*f);
        private static double Distance(Vector3 a,Vector3 b)
            =>Math.Sqrt(((double)b.x-a.x)*(b.x-a.x)+((double)b.z-a.z)*(b.z-a.z));
        private static void EmitCaps(Result result,Vector3 a,Vector3 b,
            List<(double start,double end,double hp,double hq)> caps,int maximum,double tolerance)
        {
            result.InputCapIntervals+=caps.Count;
            int first=0;
            while(first<caps.Count)
            {
                var head=caps[first];double end=head.end,height=head.hq;
                double low=double.NegativeInfinity,high=double.PositiveInfinity;
                void Constrain(double t,double h)
                {
                    double dt=t-head.start;
                    low=Math.Max(low,(h-tolerance-head.hp)/dt);
                    high=Math.Min(high,(h+tolerance-head.hp)/dt);
                }
                Constrain(end,height);int last=first;
                while(tolerance>0&&last+1<caps.Count)
                {
                    var next=caps[last+1];
                    // Exact adjacency: never span skipped, excluded or missing intervals.
                    if(next.start!=end)break;
                    double slope=(next.hq-head.hp)/(next.end-head.start);
                    double atStart=head.hp+slope*(next.start-head.start);
                    if(slope<low||slope>high||Math.Abs(atStart-next.hp)>tolerance)break;
                    Constrain(next.start,next.hp);Constrain(next.end,next.hq);
                    end=next.end;height=next.hq;last++;result.MergedCapIntervals++;
                }
                // A chord differs linearly from each original cap interval, so
                // checking both endpoints bounds the entire original lower edge.
                double finalSlope=(height-head.hp)/(end-head.start);
                for(int i=first;i<=last;i++)
                {
                    var part=caps[i];
                    result.MaximumSimplificationErrorMeters=Math.Max(result.MaximumSimplificationErrorMeters,
                        Math.Max(Math.Abs(head.hp+finalSlope*(part.start-head.start)-part.hp),
                            Math.Abs(head.hp+finalSlope*(part.end-head.start)-part.hq)));
                }
                AddCap(result,a,b,head.start,end,head.hp,height,maximum);first=last+1;
            }
        }
        private static void AddCap(Result result,Vector3 a,Vector3 b,double start,double end,double hp,double hq,int maximum)
        {
            var p=Vector3.Lerp(a,b,(float)start);var q=Vector3.Lerp(a,b,(float)end);
            double dp=p.y-hp,dq=q.y-hq;
            if(Math.Max(Math.Abs(dp),Math.Abs(dq))<0.0001)return;
            if(dp*dq<0)
            {
                double middle=start+(end-start)*dp/(dp-dq);
                // Separate a crossing of the terrain and road plane to avoid a
                // self-intersecting quad. Each side is emitted once.
                double hm=hp+(hq-hp)*(middle-start)/(end-start);
                Emit(result,p,Vector3.Lerp(a,b,(float)middle),hp,hm,maximum);
                Emit(result,Vector3.Lerp(a,b,(float)middle),q,hm,hq,maximum);
            }
            else Emit(result,p,q,hp,hq,maximum);
        }
        private static void Emit(Result result,Vector3 p,Vector3 q,double hp,double hq,int maximum)
        {
            if(Distance(p,q)<0.0001)return;
            if(result.Mesh.Triangles.Count/3+4>maximum)throw new ArgumentException("Road bank output triangle budget exceeded.");
            var bottomP=new Vector3(p.x,(float)hp,p.z);var bottomQ=new Vector3(q.x,(float)hq,q.z);
            var vertices=new[]{p,q,bottomQ,bottomP};
            // Separate vertices give each side its own normal. Walls are visible
            // and collidable both from the road cut and from a raised shoulder.
            for(int side=0;side<2;side++)
            {
                int n=result.Mesh.Vertices.Count;result.Mesh.Vertices.AddRange(vertices);
                if(side==0)result.Mesh.Triangles.AddRange(new[]{n,n+1,n+2,n,n+2,n+3});
                else result.Mesh.Triangles.AddRange(new[]{n,n+2,n+1,n,n+3,n+2});
            }
            result.Segments++;
            result.MaximumHeightDifferenceMeters=Math.Max(result.MaximumHeightDifferenceMeters,Math.Max(Math.Abs(p.y-hp),Math.Abs(q.y-hq)));
        }
    }
}
