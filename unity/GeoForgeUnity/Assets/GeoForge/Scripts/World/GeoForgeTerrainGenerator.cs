using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using LibTessDotNet;

namespace GeoForge
{
    public static class GeoForgeTerrainGenerator
    {
        public static GeoForgeMeshData BuildVisible(GeoForgeScene scene,GeoForgeTerrainSampler sampler,
            IList<GeoForgeMeshData> replacements=null)
        {
            if(scene.water_areas.Count==0&&(replacements==null||replacements.Count==0))return Build(scene,sampler);
            var boundary=scene.metadata?.selection_boundary;
            if(boundary==null)return Build(scene,sampler);
            var tess=new Tess();
            Add(tess,GeoForgeTriangulator.Prepare(boundary),false);
            foreach(var water in scene.water_areas)if(water?.polygon!=null)Add(tess,GeoForgeTriangulator.Prepare(water.polygon),true);
            // Water subtraction is visual only. Road replacements have a separate
            // collision cutout below. No source elevations are changed.
            tess.Tessellate(WindingRule.Positive,ElementType.Polygons,3,normal:new Vec3(0,0,1));
            var flat=new GeoForgeMeshData();
            foreach(var v in tess.Vertices??new ContourVertex[0])flat.Vertices.Add(new Vector3(v.Position.X,0,v.Position.Y));
            for(int i=0;i<tess.ElementCount;i++)
            {
                int a=tess.Elements[3*i],b=tess.Elements[3*i+1],c=tess.Elements[3*i+2];
                if(a!=Tess.Undef&&b!=Tess.Undef&&c!=Tess.Undef)flat.AddUpTriangle(a,b,c);
            }
            var draped=sampler.Drape(flat);
            return replacements!=null&&replacements.Count>0?
                GeoForgeGroundCutout.SubtractPreservingPlanes(draped,replacements):draped;
        }
        public static GeoForgeMeshData BuildCollision(GeoForgeScene scene,GeoForgeTerrainSampler sampler,
            IList<GeoForgeMeshData> replacements)
        {
            if(replacements==null||replacements.Count==0)return Build(scene,sampler);
            if(scene.metadata?.selection_boundary==null)throw new System.ArgumentException("Road replacement terrain requires a selection boundary.");
            return GeoForgeGroundCutout.SubtractPreservingPlanes(Build(scene,sampler),replacements);
        }
        private static void Add(Tess tess,GeoForgeTriangulator.Polygon polygon,bool subtract)
        {
            foreach(var ring in polygon.Rings)
            {
                var points=subtract?ring.AsEnumerable().Reverse():ring;
                tess.AddContour(points.Select(p=>new ContourVertex{Position=new Vec3(p.x,p.z,0)}).ToArray());
            }
        }
        public static GeoForgeMeshData Build(GeoForgeScene scene,GeoForgeTerrainSampler sampler)
        {
            var data=sampler.Data;var mesh=new GeoForgeMeshData();
            int nx=data.resolution_x,ny=data.resolution_y;
            for(int z=0;z<ny;z++)for(int x=0;x<nx;x++)
                mesh.Vertices.Add(new Vector3((float)(data.origin[0]+x*data.cell_size[0]),(float)data.heights[z*nx+x],(float)(data.origin[1]+z*data.cell_size[1])));
            var boundary=scene.metadata?.selection_boundary;
            var ring=boundary==null?null:GeoForgeTriangulator.Prepare(boundary).Rings[0];
            for(int z=0;z<ny-1;z++)for(int x=0;x<nx-1;x++)
            {
                int a=z*nx+x,b=a+1,c=a+nx,d=c+1;
                Triangle(mesh,a,b,d,ring,data.valid_mask);Triangle(mesh,a,d,c,ring,data.valid_mask);
            }
            return mesh;
        }
        private static float Side(Vector3 a,Vector3 b,Vector3 p)=>(b.x-a.x)*(p.z-a.z)-(b.z-a.z)*(p.x-a.x);
        private static void Triangle(GeoForgeMeshData mesh,int a,int b,int c,List<Vector3> boundary,bool[] mask)
        {
            if(boundary==null||(mask[a]&&mask[b]&&mask[c])){mesh.AddUpTriangle(a,b,c);return;}
            var polygon=new List<Vector3>{mesh.Vertices[a],mesh.Vertices[b],mesh.Vertices[c]};
            // Input selections are convex (projected bbox or circle). Clip only terrain border triangles;
            // interpolated Y stays on the same triangle plane as SampleHeight and the collider.
            for(int j=0;j<boundary.Count&&polygon.Count>0;j++)
            {
                var output=new List<Vector3>();var u=boundary[j];var v=boundary[(j+1)%boundary.Count];
                var previous=polygon[polygon.Count-1];float ps=Side(u,v,previous);
                foreach(var current in polygon)
                {
                    float cs=Side(u,v,current);
                    if((cs>=0)!=(ps>=0))output.Add(Vector3.Lerp(previous,current,ps/(ps-cs)));
                    if(cs>=0)output.Add(current);previous=current;ps=cs;
                }
                polygon=output;
            }
            if(polygon.Count<3)return;
            int offset=mesh.Vertices.Count;mesh.Vertices.AddRange(polygon);
            for(int i=1;i<polygon.Count-1;i++)
                if(Vector3.Cross(polygon[i]-polygon[0],polygon[i+1]-polygon[0]).sqrMagnitude>1e-12f)
                    mesh.AddUpTriangle(offset,offset+i,offset+i+1);
        }
    }
}
