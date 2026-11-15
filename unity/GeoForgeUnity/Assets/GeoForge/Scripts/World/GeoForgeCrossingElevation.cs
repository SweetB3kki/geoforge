using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace GeoForge
{
    /// <summary>Explicit crossing elevation only; no surface subtraction or priority resolver.</summary>
    public static class GeoForgeCrossingElevation
    {
        public static bool Applies(GeoForgeRoad road) => road.road_subtype=="crossing" &&
            (road.road_category=="pedestrian" || road.road_category=="cycle") && !road.bridge && !road.tunnel;

        public static Func<float,float,float> Create(GeoForgeRoad road,
            IDictionary<GeoForgeRoad,GeoForgeMeshData> meshes,GeoForgeRoadGeometrySettings settings)
        {
            var faces=new List<(Vector3 a,Vector3 b,Vector3 c)>();
            var bins=new Dictionary<(int,int),List<int>>();
            const float cell=4,transition=3;
            float minX=(float)road.vertical_profile.points.Min(p=>p[0])-(float)road.width-transition;
            float maxX=(float)road.vertical_profile.points.Max(p=>p[0])+(float)road.width+transition;
            float minZ=(float)road.vertical_profile.points.Min(p=>p[1])-(float)road.width-transition;
            float maxZ=(float)road.vertical_profile.points.Max(p=>p[1])+(float)road.width+transition;
            foreach(var item in meshes.Where(p=>p.Key.road_category=="automotive" && !p.Key.bridge &&
                !p.Key.tunnel && p.Key.layer==road.layer)) {
                var m=item.Value;
                for(int i=0;i<m.Triangles.Count;i+=3) {
                    var a=m.Vertices[m.Triangles[i]];var b=m.Vertices[m.Triangles[i+1]];var c=m.Vertices[m.Triangles[i+2]];
                    if(Math.Max(a.x,Math.Max(b.x,c.x))<minX||Math.Min(a.x,Math.Min(b.x,c.x))>maxX||
                        Math.Max(a.z,Math.Max(b.z,c.z))<minZ||Math.Min(a.z,Math.Min(b.z,c.z))>maxZ)continue;
                    if(Math.Abs(Side(a,b,c.x,c.z))<1e-10)continue;
                    int id=faces.Count;faces.Add((a,b,c));
                    int xmin=(int)Math.Floor((Math.Min(a.x,Math.Min(b.x,c.x))-transition)/cell);
                    int xmax=(int)Math.Floor((Math.Max(a.x,Math.Max(b.x,c.x))+transition)/cell);
                    int zmin=(int)Math.Floor((Math.Min(a.z,Math.Min(b.z,c.z))-transition)/cell);
                    int zmax=(int)Math.Floor((Math.Max(a.z,Math.Max(b.z,c.z))+transition)/cell);
                    for(int z=zmin;z<=zmax;z++)for(int x=xmin;x<=xmax;x++) {
                        if(!bins.TryGetValue((x,z),out var ids)){ids=new List<int>();bins.Add((x,z),ids);}ids.Add(id);
                    }
                }
            }
            float offset=GeoForgeRoadNetworkBuilder.Elevation(road,settings);
            return (x,z)=> {
                float own=GeoForgeRoadProfileSurface.Height(road.vertical_profile,x,z);
                if(!Applies(road)||!bins.TryGetValue(((int)Math.Floor(x/cell),(int)Math.Floor(z/cell)),out var ids))return own;
                double nearest=transition,selected=0;bool found=false;
                foreach(int i in ids) {
                    var t=faces[i];double det=Side(t.a,t.b,t.c.x,t.c.z);
                    double u=Side(t.b,t.c,x,z)/det,v=Side(t.c,t.a,x,z)/det,w=1-u-v;
                    double distance,y;
                    if(u>=-1e-7&&v>=-1e-7&&w>=-1e-7) {distance=0;y=u*t.a.y+v*t.b.y+w*t.c.y;}
                    else {
                        var e1=Edge(t.a,t.b,x,z);var e2=Edge(t.b,t.c,x,z);var e3=Edge(t.c,t.a,x,z);
                        var e=e1.distance<e2.distance?e1:e2;if(e3.distance<e.distance)e=e3;
                        distance=e.distance;y=e.height;
                    }
                    if(distance<nearest-1e-8 || (Math.Abs(distance-nearest)<1e-8&&y>selected)) {
                        found=true;nearest=distance;selected=y;
                    }
                }
                if(!found)return own;
                double blend=1-nearest/transition;blend=blend*blend*(3-2*blend);
                // 5 mm intentional rendering separation from the actual road plane.
                return (float)(own*(1-blend)+(selected+0.005-offset)*blend);
            };
        }
        private static double Side(Vector3 a,Vector3 b,double x,double z) =>
            ((double)b.x-a.x)*(z-a.z)-((double)b.z-a.z)*(x-a.x);
        private static (double distance,double height) Edge(Vector3 a,Vector3 b,float x,float z) {
            double dx=b.x-a.x,dz=b.z-a.z,length=dx*dx+dz*dz;
            double t=length==0?0:Math.Max(0,Math.Min(1,((x-a.x)*dx+(z-a.z)*dz)/length));
            double ex=x-a.x-t*dx,ez=z-a.z-t*dz;
            return (Math.Sqrt(ex*ex+ez*ez),a.y+t*(b.y-a.y));
        }
    }
}
