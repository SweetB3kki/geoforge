using System;
using System.Linq;
using System.Collections.Generic;
using UnityEngine;

namespace GeoForge
{
    /// <summary>Local-meter heights on the same SW-NE cell triangles used by the terrain mesh.</summary>
    public sealed class GeoForgeTerrainSampler
    {
        public readonly GeoForgeTerrainData Data;
        public bool Available => Data != null && Data.available;
        public float CellSize => Available ? (float)Math.Min(Data.cell_size[0],Data.cell_size[1]) : 10;
        public GeoForgeTerrainSampler(GeoForgeScene scene)
        {
            Data=scene.terrain;
            if(!Available)return;
            int nx=Data.resolution_x,ny=Data.resolution_y;
            if(nx<3||ny<3||nx>513||ny>513||Data.heights==null||Data.heights.Length!=nx*ny||
                Data.valid_mask==null||Data.valid_mask.Length!=nx*ny||!Data.valid_mask.Any(v=>v)||
                Data.origin==null||Data.origin.Length!=3||Data.cell_size==null||Data.cell_size.Length!=2||
                Data.heights.Any(v=>double.IsNaN(v)||double.IsInfinity(v))||
                Data.origin.Any(v=>double.IsNaN(v)||double.IsInfinity(v))||
                Data.cell_size.Any(v=>double.IsNaN(v)||double.IsInfinity(v)||v<=0))throw new ArgumentException("Invalid terrain grid.");
            if(Data.sampling!="south_to_north_rows_west_to_east_columns")throw new ArgumentException("Unknown terrain orientation.");
            var b=scene.bounds;
            if(b==null||Math.Abs(Data.origin[0]-b.min_x)>0.01||Math.Abs(Data.origin[1]-b.min_y)>0.01||
                Math.Abs(Data.origin[0]+Data.cell_size[0]*(nx-1)-b.max_x)>0.01||
                Math.Abs(Data.origin[1]+Data.cell_size[1]*(ny-1)-b.max_y)>0.01)throw new ArgumentException("Terrain bounds mismatch.");
        }
        public float SampleHeight(float x,float z)
        {
            if(!Available)return 0;
            float gx=Mathf.Clamp((float)((x-Data.origin[0])/Data.cell_size[0]),0,Data.resolution_x-1);
            float gz=Mathf.Clamp((float)((z-Data.origin[1])/Data.cell_size[1]),0,Data.resolution_y-1);
            int ix=Math.Min((int)gx,Data.resolution_x-2),iz=Math.Min((int)gz,Data.resolution_y-2);
            float u=gx-ix,v=gz-iz;int k=iz*Data.resolution_x+ix;
            float a=(float)Data.heights[k],b=(float)Data.heights[k+1],c=(float)Data.heights[k+Data.resolution_x],d=(float)Data.heights[k+Data.resolution_x+1];
            return u>=v ? a+(b-a)*u+(d-b)*v : a+(d-c)*u+(c-a)*v;
        }
        public float PolygonHeight(GeoForgePolygon polygon,bool interior=false)
        {
            if(!Available)return 0;
            var values=polygon.exterior.Take(polygon.exterior.Length-1).Select(p=>SampleHeight((float)p[0],(float)p[1])).ToList();
            if(interior)
            {
                float minX=(float)polygon.exterior.Min(p=>p[0]),maxX=(float)polygon.exterior.Max(p=>p[0]);
                float minZ=(float)polygon.exterior.Min(p=>p[1]),maxZ=(float)polygon.exterior.Max(p=>p[1]);
                float step=Mathf.Max(CellSize,Mathf.Max(maxX-minX,maxZ-minZ)/32);
                for(float z=minZ;z<=maxZ;z+=step)for(float x=minX;x<=maxX;x+=step)
                    if(GeoForgeSpawnManager.Contains(polygon,x,z))values.Add(SampleHeight(x,z));
            }
            values.Sort();return values[values.Count/2];
        }
        public GeoForgeMeshData Drape(GeoForgeMeshData source,int maximumTriangles=int.MaxValue)
        {
            if(!Available)return source;
            var result=new GeoForgeMeshData();
            // Intersect each overlay triangle with DEM cell triangles. Sampling vertices alone
            // is insufficient: a long overlay triangle otherwise cuts through terrain between nodes.
            for(int i=0;i<source.Triangles.Count;i+=3)
            {
                var points=new List<Vector3>{source.Vertices[source.Triangles[i]],source.Vertices[source.Triangles[i+1]],source.Vertices[source.Triangles[i+2]]};
                int xmin=Cell(points.Min(p=>p.x),0),xmax=Cell(points.Max(p=>p.x),0);
                int zmin=Cell(points.Min(p=>p.z),1),zmax=Cell(points.Max(p=>p.z),1);
                for(int z=zmin;z<=zmax;z++)for(int x=xmin;x<=xmax;x++)
                {
                    float x0=(float)(Data.origin[0]+x*Data.cell_size[0]),x1=(float)(Data.origin[0]+(x+1)*Data.cell_size[0]);
                    float z0=(float)(Data.origin[1]+z*Data.cell_size[1]),z1=(float)(Data.origin[1]+(z+1)*Data.cell_size[1]);
                    var a=new Vector3(x0,0,z0);var b=new Vector3(x1,0,z0);var c=new Vector3(x1,0,z1);var d=new Vector3(x0,0,z1);
                    var cell=Clip(Clip(Clip(Clip(points,a,b),b,c),c,d),d,a);
                    Emit(Clip(cell,a,c),result);Emit(Clip(cell,c,a),result);
                    if(result.Triangles.Count/3>maximumTriangles)throw new GeoForgeTriangleBudgetException();
                }
            }
            return result;
        }
        private int Cell(float coordinate,int axis)
        {
            int count=axis==0?Data.resolution_x:Data.resolution_y;
            return Mathf.Clamp((int)Math.Floor((coordinate-Data.origin[axis])/Data.cell_size[axis]),0,count-2);
        }
        /// <summary>Check every vertex of the DEM/overlay intersection, not just a few samples.
        /// Both surfaces are affine on these pieces, so extrema occur at their vertices.</summary>
        public bool ConformsEverywhere(GeoForgeMeshData placed,float offset,float tolerance,int workBudget)
        {
            if(!Available)return true;
            int work=0;
            for(int i=0;i<placed.Triangles.Count;i+=3)
            {
                var a=placed.Vertices[placed.Triangles[i]];var b=placed.Vertices[placed.Triangles[i+1]];var c=placed.Vertices[placed.Triangles[i+2]];
                double det=(b.z-c.z)*(double)(a.x-c.x)+(c.x-b.x)*(double)(a.z-c.z);
                if(Math.Abs(det)<1e-10)return false;
                var points=new List<Vector3>{a,b,c};
                int xmin=Cell(points.Min(p=>p.x),0),xmax=Cell(points.Max(p=>p.x),0),zmin=Cell(points.Min(p=>p.z),1),zmax=Cell(points.Max(p=>p.z),1);
                for(int z=zmin;z<=zmax;z++)for(int x=xmin;x<=xmax;x++)
                {
                    float x0=(float)(Data.origin[0]+x*Data.cell_size[0]),x1=(float)(Data.origin[0]+(x+1)*Data.cell_size[0]);
                    float z0=(float)(Data.origin[1]+z*Data.cell_size[1]),z1=(float)(Data.origin[1]+(z+1)*Data.cell_size[1]);
                    var p0=new Vector3(x0,0,z0);var p1=new Vector3(x1,0,z0);var p2=new Vector3(x1,0,z1);var p3=new Vector3(x0,0,z1);
                    var cell=Clip(Clip(Clip(Clip(points,p0,p1),p1,p2),p2,p3),p3,p0);
                    foreach(var polygon in new[]{Clip(cell,p0,p2),Clip(cell,p2,p0)})foreach(var p in polygon)
                    {
                        if(++work>workBudget)return false;
                        double u=((b.z-c.z)*(double)(p.x-c.x)+(c.x-b.x)*(double)(p.z-c.z))/det;
                        double v=((c.z-a.z)*(double)(p.x-c.x)+(a.x-c.x)*(double)(p.z-c.z))/det;
                        double y=u*a.y+v*b.y+(1-u-v)*c.y;
                        if(Math.Abs(y-SampleHeight(p.x,p.z)-offset)>tolerance)return false;
                    }
                }
            }
            return true;
        }
        private static float Side(Vector3 a,Vector3 b,Vector3 p)=>(b.x-a.x)*(p.z-a.z)-(b.z-a.z)*(p.x-a.x);
        private static List<Vector3> Clip(List<Vector3> polygon,Vector3 a,Vector3 b)
        {
            var output=new List<Vector3>();if(polygon.Count==0)return output;
            var previous=polygon[polygon.Count-1];float ps=Side(a,b,previous);
            foreach(var current in polygon)
            {
                float cs=Side(a,b,current);
                if((cs>=0)!=(ps>=0))output.Add(Vector3.Lerp(previous,current,ps/(ps-cs)));
                if(cs>=0)output.Add(current);previous=current;ps=cs;
            }
            return output;
        }
        private void Emit(List<Vector3> polygon,GeoForgeMeshData mesh)
        {
            if(polygon.Count<3)return;
            int k=mesh.Vertices.Count;
            foreach(var p in polygon)mesh.Vertices.Add(p+Vector3.up*SampleHeight(p.x,p.z));
            for(int i=1;i<polygon.Count-1;i++)
                if(Mathf.Abs(Vector3.Cross(polygon[i]-polygon[0],polygon[i+1]-polygon[0]).y)>1e-8f)mesh.AddUpTriangle(k,k+i,k+i+1);
        }
    }
}
