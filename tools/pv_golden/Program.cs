// PV golden CLI (E-P0-3). Runs the ORIGINAL client code path
//   CLevelList.UpdateNewMapData(levelJSON) -> new CLevel + CLayerList(map) -> ShuffleEmptyTiles(cLevel)
// on each input case and dumps the t0 assignment in client traversal order.
//
// Usage (from repo root):
//   dotnet run --project tools/pv_golden -- all                 # regenerate every golden file (default paths)
//   dotnet run --project tools/pv_golden -- case <input.json>   # print one case result to stdout
//   dotnet run --project tools/pv_golden -- rng <out.json>      # G1 WELL512 raw-output golden only
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using SimpleJSON;

static class Program
{
    static readonly uint[] RngSeeds = { 1u, 12345u, 625901u, 2147483647u, 4294967295u };
    const int RngCount = 1000;

    static readonly string RepoRoot = FindRepoRoot();
    static readonly string GoldenDir = Path.Combine(RepoRoot, "backend", "tests", "golden", "pv_t0");
    static readonly string MetaPath = Path.Combine(RepoRoot, "tools", "pv_golden", "Generated", "extract_meta.json");

    static int Main(string[] args)
    {
        string cmd = args.Length > 0 ? args[0] : "all";
        try
        {
            switch (cmd)
            {
                case "all":
                    WriteRngGolden(Path.Combine(GoldenDir, "rng_well512.json"));
                    RunAll(Path.Combine(GoldenDir, "inputs"), Path.Combine(GoldenDir, "expected"));
                    break;
                case "case":
                    Console.WriteLine(ToJson(RunCase(args[1], Path.GetFileName(args[1]))));
                    break;
                case "rng":
                    WriteRngGolden(args[1]);
                    break;
                default:
                    Console.Error.WriteLine("usage: all | case <input.json> | rng <out.json>");
                    return 2;
            }
            CheckShimHealth();
            return 0;
        }
        catch (Exception e)
        {
            Console.Error.WriteLine("PvGolden FAILED: " + e.Message);
            return 1;
        }
    }

    static string FindRepoRoot()
    {
        var d = new DirectoryInfo(AppContext.BaseDirectory);
        while (d != null && !File.Exists(Path.Combine(d.FullName, "tools", "pv_golden", "PvGolden.csproj")))
            d = d.Parent;
        if (d == null) throw new InvalidOperationException("repo root not found");
        return d.FullName;
    }

    // ---------------------------------------------------------------- G1: WELL512 raw output
    static uint RawNext(zWellRandom r)
    {
        var m = typeof(zWellRandom).GetMethod("_rand", BindingFlags.NonPublic | BindingFlags.Instance);
        return (uint)m.Invoke(r, null);
    }

    static void WriteRngGolden(string path)
    {
        var seeds = new JsonArray();
        foreach (uint s in RngSeeds)
        {
            var r = new zWellRandom(s);
            var vals = new JsonArray();
            for (int i = 0; i < RngCount; i++) vals.Add(RawNext(r));
            seeds.Add(new JsonObject { ["seed"] = s, ["raw"] = vals });
        }
        var root = Header("rng");
        root["description"] = "zWellRandom(seed)._rand() raw uint32 outputs, first 1000 per seed. seed 4294967295 == (uint)(-1).";
        root["seeds"] = seeds;
        File.WriteAllText(path, ToJson(root));
        Console.WriteLine($"rng golden -> {Rel(path)}");
    }

    // ---------------------------------------------------------------- G2: t0 assignment cases
    static void RunAll(string inputsDir, string expectedDir)
    {
        Directory.CreateDirectory(expectedDir);
        var files = Directory.GetFiles(inputsDir, "*.json").OrderBy(f => f, StringComparer.Ordinal).ToList();
        var manifestCases = new JsonArray();
        int failedChecks = 0;
        foreach (var f in files)
        {
            string name = Path.GetFileName(f);
            JsonObject result = RunCase(f, name);
            File.WriteAllText(Path.Combine(expectedDir, name), ToJson(result));

            var runs = result["results"].AsArray();
            int pass = runs.Count(r => r["selfCheck"]["ok"].GetValue<bool>());
            int threw = runs.Count(r => r["exception"] != null);
            // per-run outcome: pass | fail (assigned, per-type check fails) | exception (client throws) | nondeterministic (seed AsInt 0)
            var outcomes = runs.Select(Outcome).ToList();
            var expects = result["expectPerRun"] is JsonArray ea
                ? ea.Select(x => x.GetValue<string>()).ToList()
                : Enumerable.Repeat(result["expectSelfCheck"]?.GetValue<string>() ?? "pass", runs.Count).ToList();
            string expect = result["expectPerRun"] != null ? "perRun" : expects.FirstOrDefault() ?? "pass";
            bool asExpected = expects.Count == outcomes.Count && expects.SequenceEqual(outcomes);
            if (!asExpected) failedChecks++;
            manifestCases.Add(new JsonObject
            {
                ["file"] = name,
                ["kind"] = result["kind"].DeepClone(),
                ["runs"] = runs.Count,
                ["t0Count"] = runs.Count > 0 ? runs[0]["selfCheck"]["t0Count"].DeepClone() : 0,
                ["selfCheckOk"] = pass,
                ["clientThrows"] = threw,
                ["expectSelfCheck"] = expect,
                ["outcomes"] = new JsonArray(outcomes.Select(o => (JsonNode)o).ToArray()),
                ["asExpected"] = asExpected,
            });
            Console.WriteLine($"{name}: runs={runs.Count} selfCheckOk={pass} expect={expect} {(asExpected ? "OK" : "UNEXPECTED")}");
        }
        var manifest = Header("manifest");
        manifest["cases"] = manifestCases;
        manifest["unityRandomCallers"] = new JsonArray(UnityEngine.Random.Callers.OrderBy(x => x, StringComparer.Ordinal).Select(x => (JsonNode)x).ToArray());
        File.WriteAllText(Path.Combine(expectedDir, "_manifest.json"), ToJson(manifest));
        if (failedChecks > 0) throw new InvalidOperationException($"{failedChecks} case(s) did not match expectSelfCheck");
    }

    static string Outcome(JsonNode r)
    {
        if (r["nondeterministic"] != null) return "nondeterministic";
        if (r["exception"] != null) return "exception";
        return r["selfCheck"]["ok"].GetValue<bool>() ? "pass" : "fail";
    }

    static JsonObject RunCase(string path, string fileName)
    {
        string text = File.ReadAllText(path);
        JSONNode input = JSON.Parse(text);
        string levelId = input["levelId"].Value;
        if (string.IsNullOrEmpty(levelId)) throw new InvalidOperationException($"{fileName}: levelId missing");

        TileSetting.TileCountOverride = input["shim"]["tileCount"].IsNumber ? input["shim"]["tileCount"].AsInt : 16;

        var root = Header("case");
        root["caseId"] = input["caseId"].Value;
        root["kind"] = input["kind"].Value;
        root["note"] = input["note"].Value;
        root["inputFile"] = fileName;
        root["inputSha256"] = Sha256(Encoding.UTF8.GetBytes(text));
        root["levelId"] = levelId;
        if (input["expectSelfCheck"].IsString) root["expectSelfCheck"] = input["expectSelfCheck"].Value;
        if (input["expectPerRun"].IsArray) root["expectPerRun"] = JsonNode.Parse(input["expectPerRun"].ToString());
        root["tileCountShim"] = TileSetting.TileCountOverride;

        JSONNode runsNode = input["runs"];
        int runCount = runsNode.IsArray ? runsNode.Count : 1;
        bool dumpRng = input["dumpRng"].AsBool;
        var results = new JsonArray();
        for (int ri = 0; ri < runCount; ri++)
        {
            JSONNode overrides = runsNode.IsArray ? runsNode[ri] : new JSONObject();
            results.Add(RunOne(text, levelId, overrides, dumpRng, fileName));
        }
        root["results"] = results;
        return root;
    }

    static JSONNode FreshRow(string inputText, JSONNode overrides)
    {
        // re-parse every run: the shuffle mutates CTile objects only, but a fresh parse keeps runs independent
        JSONNode row = JSON.Parse(inputText)["row"];
        foreach (var kv in overrides) row[kv.Key] = kv.Value;
        return row;
    }

    static JsonObject RunOne(string inputText, string levelId, JSONNode overrides, bool dumpRng, string fileName)
    {
        // ---- 1) t0 locations, using the ORIGINAL GetEmptyTileList(false) on an untouched parse
        JSONNode preRow = FreshRow(inputText, overrides);
        var pre = new DB_Level.CLevel();
        pre.xLayerList = new DB_Level.CLayerList(preRow["map"]);
        var where = IndexTiles(pre);
        var locs = pre.GetEmptyTileList(false).Select(t => where[t]).ToList();

        // ---- 2) real client path: UpdateNewMapData -> ShuffleEmptyTiles
        JSONNode row = FreshRow(inputText, overrides);
        int seedInt = row["randSeed"].AsEncrypt.AsInt;
        if (seedInt == 0)
        {
            // client: zWellRandom.Seed(0) -> time-based seed (seconds). Not reproducible -> no types recorded.
            return new JsonObject
            {
                ["overrides"] = JsonNode.Parse(overrides.ToString()),
                ["effective"] = new JsonObject { ["randSeed"] = 0, ["seedUint"] = 0u },
                ["positions"] = new JsonArray(locs.Select(l => (JsonNode)new JsonArray(l.layerKey, l.pos, l.inner)).ToArray()),
                ["layerIndexByKey"] = LayerIndexByKey(pre),
                ["types"] = null,
                ["nondeterministic"] = "randSeed AsInt == 0 -> zWellRandom time-based seed",
                ["selfCheck"] = new JsonObject { ["ok"] = false, ["t0Count"] = locs.Count },
            };
        }
        var levelJSON = new JSONObject();
        levelJSON.Add(levelId, row);
        var list = GameController.inst.DB_Level.LevelList;
        list.Clear();
        try
        {
            list.UpdateNewMapData(levelJSON);
        }
        catch (Exception e)
        {
            // the client itself throws here (e.g. t0 count not coverable by emptyLen/3 sets) -> record as the golden outcome
            var frame = new System.Diagnostics.StackTrace(e, true).GetFrames()
                .FirstOrDefault(fr => (fr.GetFileName() ?? "").EndsWith("DB_Level.cs", StringComparison.Ordinal));
            return new JsonObject
            {
                ["overrides"] = JsonNode.Parse(overrides.ToString()),
                ["effective"] = new JsonObject { ["randSeed"] = seedInt, ["seedUint"] = (uint)seedInt },
                ["positions"] = new JsonArray(locs.Select(l => (JsonNode)new JsonArray(l.layerKey, l.pos, l.inner)).ToArray()),
                ["layerIndexByKey"] = LayerIndexByKey(pre),
                ["types"] = null,
                ["exception"] = new JsonObject
                {
                    ["type"] = e.GetType().Name,
                    ["at"] = frame == null ? null : $"DB_Level.cs:{frame.GetFileLineNumber()} {frame.GetMethod()?.Name}",
                },
                ["selfCheck"] = new JsonObject { ["ok"] = false, ["t0Count"] = locs.Count, ["t0CountMod3"] = locs.Count % 3, ["clientThrows"] = true },
            };
        }
        DB_Level.CLevel lv = list[levelId];

        // ---- 3) read assignment back at the same locations
        var types = new JsonArray();
        var positions = new JsonArray();
        var assigned = new int[17];
        bool allAssigned = true;
        foreach (var loc in locs)
        {
            DB_Level.CTile t = Locate(lv, loc);
            int id = t.tileIDNum;
            if (id < 1 || id > 16) allAssigned = false; else assigned[id]++;
            types.Add(id);
            positions.Add(new JsonArray(loc.layerKey, loc.pos, loc.inner));
        }

        // whole level after assignment (explicit + assigned), per type
        var total = new int[17];
        int unresolved = 0;
        foreach (var t in AllPlayable(lv))
        {
            int id = t.tileIDNum;
            if (id >= 1 && id <= 16) total[id]++; else unresolved++;
        }
        var nonMul = new JsonArray();
        for (int i = 1; i <= 16; i++) if (total[i] % 3 != 0) nonMul.Add(i);
        // t0Count itself need not be %3: toAdd padding may consume part of it (s17). Validity = every type total %3.
        bool ok = allAssigned && unresolved == 0 && nonMul.Count == 0 && types.Count == locs.Count;

        var eff = new JsonObject
        {
            ["randSeed"] = seedInt,
            ["seedUint"] = (uint)seedInt,
            ["useTileCount"] = lv.xUseTileCount.AsInt,
            ["unlockTile"] = lv.xUnlockTile.AsInt,
            ["shuffleTile"] = lv.xShuffleTile.AsInt,
            ["typeImbalance"] = lv.xTypeImbalance.AsInt,
            ["maxTileIndex"] = lv.xUseTileCount.AsInt > 0 ? lv.xUseTileCount.AsInt : TileSetting.TileCountOverride - 1,
        };

        var res = new JsonObject
        {
            ["overrides"] = JsonNode.Parse(overrides.ToString()),
            ["effective"] = eff,
            ["layerIndexByKey"] = LayerIndexByKey(lv),
            ["positions"] = positions,
            ["types"] = types,
            ["selfCheck"] = new JsonObject
            {
                ["ok"] = ok,
                ["t0Count"] = locs.Count,
                ["typesCount"] = types.Count,
                ["t0CountMod3"] = locs.Count % 3,
                ["allAssigned"] = allAssigned,
                ["unresolvedTiles"] = unresolved,
                ["assignedPerType"] = PerType(assigned),
                ["totalPerType"] = PerType(total),
                ["totalPerTypeNotMultipleOf3"] = nonMul,
            },
            ["resolvedMap"] = JsonNode.Parse(ResolvedMap(preRow["map"], lv).ToString()),
        };
        if (dumpRng)
        {
            int n = locs.Count;
            int shuffle = Math.Max(0, lv.xShuffleTile.AsInt);
            int prefix = n / 3 + lv.xUnlockTile.AsInt + 10 + 2 * (n + shuffle);  // upper bound of calls consumed
            var r = new zWellRandom((uint)seedInt);
            var raw = new JsonArray();
            for (int i = 0; i < prefix; i++) raw.Add(RawNext(r));
            res["rngRawPrefix"] = raw;
        }
        return res;
    }

    // CLayer.layerIndex (= enumeration order of layer_* keys in map JSON, DB_Level.cs:548-553) per layer key
    static JsonObject LayerIndexByKey(DB_Level.CLevel lv)
    {
        var o = new JsonObject();
        foreach (var kv in lv.xLayerList) o[kv.Key] = kv.Value.layerIndex;
        return o;
    }

    record Loc(string layerKey, string pos, int inner);

    // map every CTile object (board + container inner) to its location; layer order = layer_{i} like the client
    static Dictionary<DB_Level.CTile, Loc> IndexTiles(DB_Level.CLevel lv)
    {
        var d = new Dictionary<DB_Level.CTile, Loc>(ReferenceEqualityComparer.Instance);
        foreach (var kv in lv.xLayerList)
        {
            if (kv.Value.xTiles == null) continue;
            foreach (var tk in kv.Value.xTiles)
            {
                d[tk.Value] = new Loc(kv.Key, tk.Key, -1);
                var st = tk.Value.xTileStackInfo;
                if (st != null)
                    for (int i = 0; i < st.stackCTileList.Count; i++)
                        d[st.stackCTileList[i]] = new Loc(kv.Key, tk.Key, i);
            }
        }
        return d;
    }

    static DB_Level.CTile Locate(DB_Level.CLevel lv, Loc loc)
    {
        var t = lv.xLayerList[loc.layerKey].xTiles[loc.pos];
        return loc.inner < 0 ? t : t.xTileStackInfo.stackCTileList[loc.inner];
    }

    // every pickable tile: board tiles without container info + all container inner tiles
    static IEnumerable<DB_Level.CTile> AllPlayable(DB_Level.CLevel lv)
    {
        foreach (var layer in lv.xLayerList.Values)
        {
            if (layer.xTiles == null) continue;
            foreach (var t in layer.xTiles.Values)
            {
                if (t.xTileStackInfo != null) foreach (var s in t.xTileStackInfo.stackCTileList) yield return s;
                else yield return t;
            }
        }
    }

    // input map with every tile id written explicitly; containers become [cnt, "id0_id1_..."] (index 0 = bottom)
    static JSONNode ResolvedMap(JSONNode map, DB_Level.CLevel lv)
    {
        JSONNode outMap = JSON.Parse(map.ToString());
        foreach (var kv in lv.xLayerList)
        {
            if (kv.Value.xTiles == null) continue;
            JSONNode tiles = outMap[kv.Key]["tiles"];
            foreach (var tk in kv.Value.xTiles)
            {
                var t = tk.Value;
                JSONNode node = tiles[tk.Key];
                if (t.xTileStackInfo != null)
                {
                    var ids = t.xTileStackInfo.stackCTileList.Select(s => s.xTileID.AsString);
                    var arr = new JSONArray();
                    arr.Add(new JSONNumber(t.xTileStackInfo.stackCTileList.Count));
                    arr.Add(new JSONString(string.Join("_", ids)));
                    node[2] = arr;
                }
                else
                {
                    node[0] = new JSONString(t.xTileID.AsString);
                }
            }
        }
        return outMap;
    }

    static JsonObject PerType(int[] c)
    {
        var o = new JsonObject();
        for (int i = 1; i <= 16; i++) if (c[i] > 0) o[i.ToString()] = c[i];
        return o;
    }

    // ---------------------------------------------------------------- common
    static JsonObject Header(string type)
    {
        var meta = JsonNode.Parse(File.ReadAllText(MetaPath));
        return new JsonObject
        {
            ["format"] = "pv_t0_golden/v1",
            ["type"] = type,
            ["generator"] = "tools/pv_golden (dotnet, original DB_Level.cs extract + zWellRandom.cs)",
            ["distVer"] = meta["distVer"].DeepClone(),
            ["sourceSha256"] = meta["sourceSha256"].DeepClone(),
            ["zWellRandomSha256"] = meta["zWellRandomSha256"].DeepClone(),
            ["authority"] = "provisional (G2). Final authority = Unity editor dump (G3, pending approval).",
        };
    }

    static void CheckShimHealth()
    {
        if (UnityEngine.Debug.ErrorCount > 0)
            throw new InvalidOperationException("Debug.LogError fired (SimpleJSON/spEncrypt verify failure?): " + string.Join(" | ", UnityEngine.Debug.Errors));
        var allowed = new[] { "SimpleJSON.", "spEncrypt", "spString", "spInt", "spDouble", "spLong", "spBool", "spFloat", "spShort", "spULong" };
        var bad = UnityEngine.Random.Callers.Where(c => !allowed.Any(a => c.StartsWith(a, StringComparison.Ordinal))).ToList();
        if (bad.Count > 0)
            throw new InvalidOperationException("UnityEngine.Random.Range called from unexpected code: " + string.Join(", ", bad));
    }

    static string Sha256(byte[] b) => Convert.ToHexString(SHA256.HashData(b)).ToLowerInvariant();
    static string Rel(string p) => Path.GetRelativePath(RepoRoot, p);
    static string ToJson(JsonNode n) => n.ToJsonString() + "\n";
}
