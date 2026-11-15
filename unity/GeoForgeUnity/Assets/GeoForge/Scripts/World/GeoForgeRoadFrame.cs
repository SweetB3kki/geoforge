using System;
using System.Collections.Generic;

namespace GeoForge
{
    /// <summary>Derived ribbon: tangent/lateral frames share one Y per station.
    /// Coordinates are east,north,up. This class never samples terrain.</summary>
    public sealed class GeoForgeRoadFrame
    {
        private struct Face
        {
            public double ax,az,ay,bx,bz,by,cx,cz,cy;
            public bool Height(double x,double z,out float y)
            {
                y=0;
                if(x<Math.Min(ax,Math.Min(bx,cx))-1e-5||x>Math.Max(ax,Math.Max(bx,cx))+1e-5||
                   z<Math.Min(az,Math.Min(bz,cz))-1e-5||z>Math.Max(az,Math.Max(bz,cz))+1e-5)return false;
                double det=(bz-cz)*(ax-cx)+(cx-bx)*(az-cz);
                if(Math.Abs(det)<1e-12)return false;
                double u=((bz-cz)*(x-cx)+(cx-bx)*(z-cz))/det;
                double v=((cz-az)*(x-cx)+(ax-cx)*(z-cz))/det;
                if(u< -1e-6||v< -1e-6||1-u-v< -1e-6)return false;
                y=(float)(u*ay+v*by+(1-u-v)*cy);return true;
            }
        }
        private readonly List<Face> faces=new List<Face>();
        public GeoForgeRoadFrame(GeoForgeRoadVerticalProfile profile,double halfWidth)
        {
            var p=profile.points;var left=new double[p.Length][];var right=new double[p.Length][];
            for(int i=0;i<p.Length;i++) {
                var a=p[Math.Max(0,i-1)];var b=p[Math.Min(p.Length-1,i+1)];
                double dx=b[0]-a[0],dz=b[1]-a[1],length=Math.Sqrt(dx*dx+dz*dz);
                if(length<1e-10)continue;
                // Slightly wider support covers bevel tessellation; actual
                // component blending still uses the physical half width.
                double nx=-dz/length*halfWidth*1.2,nz=dx/length*halfWidth*1.2;
                left[i]=new[]{p[i][0]+nx,p[i][1]+nz,p[i][2]};
                right[i]=new[]{p[i][0]-nx,p[i][1]-nz,p[i][2]};
            }
            for(int i=1;i<p.Length;i++) {
                if(left[i-1]==null||left[i]==null)continue;
                Add(left[i-1],right[i-1],left[i]);Add(right[i-1],right[i],left[i]);
            }
        }
        private void Add(double[] a,double[] b,double[] c)
            =>faces.Add(new Face{ax=a[0],az=a[1],ay=a[2],bx=b[0],bz=b[1],by=b[2],cx=c[0],cz=c[1],cy=c[2]});
        public bool TryHeight(float x,float z,out float y)
        {
            foreach(var f in faces)if(f.Height(x,z,out y))return true;
            y=0;return false;
        }
    }
}
