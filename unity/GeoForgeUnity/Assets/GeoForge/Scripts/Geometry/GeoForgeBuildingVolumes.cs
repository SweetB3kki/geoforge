using System;
using System.Collections.Generic;

namespace GeoForge
{
    // Pure scene-contract expansion. No GIS source knowledge belongs in this layer.
    public static class GeoForgeBuildingVolumes
    {
        public static GeoForgeBuilding Copy(GeoForgeBuilding b)
        {
            return new GeoForgeBuilding {id=b.id,parent_id=b.parent_id,footprint=b.footprint,position=b.position,
                height=b.height,min_height=b.min_height,levels=b.levels,height_source=b.height_source,
                building_type=b.building_type,source_tags=b.source_tags,resolved_tags=b.resolved_tags,
                ground_height_m=b.ground_height_m,ground_method=b.ground_method,strategy_used=b.strategy_used};
        }
        public static List<GeoForgeBuilding> Expand(List<GeoForgeBuilding> buildings)
        {
            var result=new List<GeoForgeBuilding>();
            foreach(var b in buildings)
            {
                if(b==null){result.Add(null);continue;}
                if(b.render_footprints==null)result.Add(b);
                else for(int i=0;i<b.render_footprints.Count;i++)
                {
                    var volume=Copy(b);volume.id=b.id+"/remainder/"+i;volume.parent_id=b.id;
                    volume.footprint=b.render_footprints[i];result.Add(volume);
                }
                if(b.parts!=null)foreach(var part in b.parts)
                {
                    if(part==null||part.parent_id!=b.id)throw new ArgumentException("Invalid building part parent.");
                    result.Add(part);
                }
            }
            return result;
        }
        public static GeoForgeBuilding Volume(GeoForgeBuilding building)
        {
            if(building==null||!GeoForgeCoordinateConverter.IsFinite(building.min_height)||building.min_height<0||building.min_height>=building.height)
                throw new ArgumentException("Invalid building vertical extent.");
            var result=Copy(building);result.height-=result.min_height;result.min_height=0;
            return result;
        }
        public static float Ground(GeoForgeBuilding building,GeoForgeTerrainSampler sampler)
        {
            if(!building.ground_height_m.HasValue)return sampler.PolygonHeight(building.footprint);
            double level=building.ground_height_m.Value;
            if(!GeoForgeCoordinateConverter.IsFinite(level)||Math.Abs(level)>100000)throw new ArgumentException("Invalid building ground height.");
            return (float)level;
        }
    }
}
