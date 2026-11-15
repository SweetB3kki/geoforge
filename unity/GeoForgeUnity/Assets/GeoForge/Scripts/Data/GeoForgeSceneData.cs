using System.Collections.Generic;

namespace GeoForge
{
    // JSON names deliberately match the existing Python contract, schema 1.0.
    public sealed class GeoForgeScene
    {
        public Newtonsoft.Json.Linq.JObject processing_audit;
        public GeoForgeTerrainData terrain;
        public GeoForgeMetadata metadata;
        public GeoForgeOrigin origin;
        public GeoForgeBounds bounds;
        public List<GeoForgeBuilding> buildings;
        public List<GeoForgeRoad> roads;
        public List<GeoForgeArea> water_areas;
        public List<GeoForgeArea> green_areas;
    }
    public sealed class GeoForgeTerrainData
    {
        public bool available;
        public int resolution_x,resolution_y;
        public double[] origin,cell_size,heights;
        public bool[] valid_mask;
        public double min_height,max_height,height_offset_m;
        public string sampling,source,attribution,vertical_datum;
        public string[] source_urls;
    }
    public sealed class GeoForgeMetadata
    {
        public string schema_version, source, crs, units, axes, attribution, generated_at, selection_type;
        public double origin_lat, origin_lon;
        public GeoForgePolygon selection_boundary;
        public int skipped_features, repaired_features;
    }
    public sealed class GeoForgeOrigin { public double easting, northing, altitude_m; }
    public sealed class GeoForgeBounds { public double min_x, min_y, max_x, max_y; }
    public sealed class GeoForgePolygon
    {
        public double[][] exterior;
        public double[][][] holes;
    }
    public sealed class GeoForgeBuilding
    {
        public string id, building_type;
        public string height_source="legacy";
        public GeoForgePolygon footprint;
        public double[] position;
        public double height;
        public double? levels;
        public Dictionary<string, string> source_tags;
        public Dictionary<string, string> resolved_tags;
        public List<GeoForgeBuilding> parts;
        public List<GeoForgePolygon> render_footprints;
        public string parent_id, strategy_used, ground_method;
        public double min_height;
        public double? ground_height_m;
    }
    public sealed class GeoForgeRoad
    {
        public string id, road_type;
        public string strategy_used;
        public GeoForgeRoadVerticalProfile vertical_profile;
        public double[][] path;
        public double width;
        public Dictionary<string, string> source_tags;
        // Defaults preserve legacy schema 1.0 files; Python supplies v0.2.5 semantics.
        public string road_category = "automotive";
        public string road_subtype;
        public string width_source = "legacy";
        public int? lanes, oneway;
        public string name, @ref, surface;
        public bool bridge, tunnel;
        public int? layer = 0;
        public List<string> source_ids;
        public List<string> node_ids;
        public string start_node, end_node;
        public Dictionary<string, Dictionary<string,string>> source_tags_by_id;
    }
    public sealed class GeoForgeArea
    {
        public string id, area_type;
        public string water_type, water_height_method, strategy_used;
        public double? water_level_m;
        public GeoForgePolygon polygon;
        public Dictionary<string, string> source_tags;
    }
}
