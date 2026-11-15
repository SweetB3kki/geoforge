using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace GeoForge.Editor
{
    public static class GeoForgeSectionFieldProbe
    {
        public static void Run()
        {
            foreach(string city in new[]{"moscow","sevastopol"}) {
                string folder=GeoForgeJsonLoader.ResolvePath("../../output/v05-g5/section-candidate/"+city);
                var scene=JsonConvert.DeserializeObject<GeoForgeScene>(File.ReadAllText(folder+"/scene.json"));
                var heights=GeoForgeRoadProfileSurface.CreateNetworkHeights(scene.roads,new GeoForgeRoadGeometrySettings(),true);
                var rows=new List<object>();var deltas=new List<double>();
                foreach(var r in scene.roads.Where(r=>r.road_category=="automotive"&&!r.bridge&&!r.tunnel&&r.layer==0)) {
                    var p=r.vertical_profile.points;var h=heights[r];
                    for(int i=0;i<p.Length;i++) {
                        var a=p[Math.Max(0,i-1)];var b=p[Math.Min(p.Length-1,i+1)];
                        double dx=b[0]-a[0],dz=b[1]-a[1],length=Math.Sqrt(dx*dx+dz*dz);
                        double nx=-dz/length*r.width*.4,nz=dx/length*r.width*.4;
                        double left=h((float)(p[i][0]+nx),(float)(p[i][1]+nz));
                        double center=h((float)p[i][0],(float)p[i][1]);
                        double right=h((float)(p[i][0]-nx),(float)(p[i][1]-nz));
                        double delta=Math.Max(left,Math.Max(center,right))-Math.Min(left,Math.Min(center,right));
                        deltas.Add(delta);rows.Add(new{road=r.id,station=i,xy=new[]{p[i][0],p[i][1]},leftY=left,centerY=center,rightY=right,crossSectionDelta=delta});
                    }
                }
                var sorted=deltas.OrderBy(v=>v).ToArray();
                File.WriteAllText(folder+"/cross-section-field-probe.json",JsonConvert.SerializeObject(new{
                    scope="Preflight field samples, NOT actual mesh acceptance",maxCrossSectionDelta=sorted.Last(),
                    p95CrossSectionDelta=sorted[(int)(.95*(sorted.Length-1))],meanCrossSectionDelta=deltas.Average(),stations=rows},Formatting.Indented));
                UnityEngine.Debug.Log(city+" cross-section field max="+sorted.Last()+" p95="+sorted[(int)(.95*(sorted.Length-1))]);
            }
        }
    }
}
