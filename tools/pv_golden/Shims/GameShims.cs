// Stand-ins for game types referenced by the extracted DB_Level.cs code (no game logic here).
// Risk notes (see README "shim 위험 지점"):
// - TileSetting.GetTileCount: the real value comes from the skin prefab (tileSkinGroups). It is read by
//   ShuffleEmptyTiles only when useTileCount <= 0 (maxTileIndex = GetTileCount - 1). Default 16
//   ("normal 15 + key 1" per TileSetting.cs comment); golden cases keep useTileCount > 0 except one
//   explicitly marked shim-dependent case.
// - TileSkinRotation.HasIconOrderForLevelID: live skins 0/1 both have icon_order -> true, so
//   ApplyVisualTileRemap returns before touching tiles (01 note §2). Golden inputs carry no visualTileSeed.
using System;
using System.Collections.Generic;
using SimpleJSON;
using UnityEngine;

public static class KLogger
{
    public static void Log(string message) { }
    public static void LogWarning(string message) { }
    public static void LogError(string message, bool printInDevice = false) { }
}

public class spEncryptDB
{
    public void SetChanged() { }
}

public class spItem { public spEncrypt xID; public spEncrypt xNum; }

public class Tile { }

public class TileSetting
{
    public static int TileCountOverride = 16;
    public int GetTileCount(int index = 0) => TileCountOverride;
}

public static class TileSkinRotation
{
    public static bool HasIconOrder = true;
    public static bool HasIconOrderForLevelID(string levelID) => HasIconOrder;
}

public class spGBoostMng
{
    public static spGBoostMng inst = new spGBoostMng();
    public JSONNode GetObjectArray(string name) => throw new InvalidOperationException("harness passes levelJSON explicitly");
    public void RemoveObjectArray(string name) { }
    public spItem[] JSONToItemArray(JSONNode node) => new spItem[0];
}

public class GameController
{
    public static GameController inst = new GameController();
    public DB_Level DB_Level = new DB_Level();
}

public partial class DB_Level
{
    readonly TileSetting m_TileSetting = new TileSetting();
    public TileSetting TileSetting => m_TileSetting;
    public CLevelList LevelList = new CLevelList();
}
