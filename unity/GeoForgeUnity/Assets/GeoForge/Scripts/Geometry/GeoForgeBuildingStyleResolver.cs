using System;
using System.Collections.Generic;
using UnityEngine;

namespace GeoForge
{
    public static class GeoForgeBuildingStyleResolver
    {
        private static readonly Dictionary<string,string> Named=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase)
        { {"grey","#808080"},{"gray","#808080"},{"brown","#A52A2A"},{"beige","#F5F5DC"},{"brick","#A65B43"},
          {"red","#FF0000"},{"white","#FFFFFF"},{"black","#000000"},{"blue","#0000FF"},{"green","#008000"},
          {"yellow","#FFFF00"},{"orange","#FFA500"},{"silver","#C0C0C0"} };
        public static bool TryColour(string text,out Color color)
        {
            color=Color.white;if(string.IsNullOrWhiteSpace(text))return false;
            text=text.Trim();if(Named.TryGetValue(text,out var hex))text=hex;
            if(!text.StartsWith("#")||(text.Length!=4&&text.Length!=7))return false;
            return ColorUtility.TryParseHtmlString(text,out color);
        }
        public static string Category(GeoForgeBuilding building)
        {
            switch(building.building_type??Tag(building,"building"))
            {
                case "residential":case "apartments":case "house":case "detached":case "terrace":case "dormitory":return "residential";
                case "commercial":case "retail":case "office":case "supermarket":return "commercial";
                case "industrial":case "warehouse":return "industrial";
                case "garage":case "garages":case "shed":case "service":return "small";
                case "public":case "civic":case "school":case "hospital":case "church":case "university":case "kindergarten":return "public";
                default:return "default";
            }
        }
        public static string Tag(GeoForgeBuilding building,string key)
        {
            if(building.resolved_tags!=null&&building.resolved_tags.TryGetValue(key,out var resolved))return resolved;
            return building.source_tags!=null&&building.source_tags.TryGetValue(key,out var value)?value:null;
        }
        public static Color Wall(GeoForgeBuilding building)
        {
            if(TryColour(Tag(building,"building:colour"),out var color))return color;
            switch(Tag(building,"building:material"))
            {
                case "brick":return new Color(0.64f,0.39f,0.29f);
                case "wood":return new Color(0.57f,0.44f,0.29f);
                case "glass":return new Color(0.48f,0.64f,0.70f);
            }
            switch(Category(building))
            {
                case "residential":return new Color(0.72f,0.63f,0.49f);
                case "commercial":return new Color(0.54f,0.65f,0.72f);
                case "industrial":return new Color(0.51f,0.55f,0.59f);
                case "small":return new Color(0.57f,0.50f,0.39f);
                case "public":return new Color(0.80f,0.73f,0.59f);
                default:return new Color(0.67f,0.59f,0.47f);
            }
        }
        public static Color Roof(GeoForgeBuilding building)
        {
            if(TryColour(Tag(building,"roof:colour"),out var color))return color;
            switch(Tag(building,"roof:material"))
            {
                case "roof_tiles":case "tile":case "tiles":return new Color(0.50f,0.25f,0.16f);
                case "metal":case "metal_sheet":return new Color(0.49f,0.54f,0.57f);
                default:return new Color(0.37f,0.39f,0.40f);
            }
        }
    }
}
