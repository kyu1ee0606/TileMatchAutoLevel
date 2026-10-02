// Minimal UnityEngine stand-ins so the original game sources compile under plain .NET.
// Risk notes (see README "shim 위험 지점"):
// - Random.Range is called ONLY by SimpleJSON / spEncrypt to pick obfuscation keys (m_nEncrypt).
//   The keys are XOR/additive masks that round-trip, so their value must not change logical results.
//   Program.cs records every distinct caller and fails if a caller outside those two files appears.
// - Mathf.RoundToInt mirrors Unity: (int)Math.Round(f) -> banker's rounding (MidpointRounding.ToEven).
// - Debug.LogError is counted: SimpleJSON/spEncrypt use it on tamper/verify failure, so a non-zero
//   count means a parsed value may have been replaced by ""/0. Program.cs fails the run in that case.
using System;
using System.Collections.Generic;
using System.Diagnostics;

namespace UnityEngine
{
    public class Object { }
    public class Component : Object { }
    public class Behaviour : Component { }
    public class MonoBehaviour : Behaviour { }

    [AttributeUsage(AttributeTargets.Field)]
    public sealed class SerializeField : Attribute { }

    public static class Random
    {
        // fixed seed: keeps runs reproducible (values only feed obfuscation masks)
        static readonly System.Random s_rng = new System.Random(20261002);
        public static readonly HashSet<string> Callers = new HashSet<string>();
        public static long CallCount;

        static void Track()
        {
            CallCount++;
            var frame = new StackTrace(2, false).GetFrame(0);
            var m = frame?.GetMethod();
            Callers.Add(m == null ? "?" : (m.DeclaringType?.FullName ?? "?"));
        }

        // Unity semantics: int version is [min, max)
        public static int Range(int minInclusive, int maxExclusive)
        {
            Track();
            return maxExclusive <= minInclusive ? minInclusive : s_rng.Next(minInclusive, maxExclusive);
        }

        public static float Range(float minInclusive, float maxInclusive)
        {
            Track();
            return minInclusive + (float)s_rng.NextDouble() * (maxInclusive - minInclusive);
        }
    }

    public static class Mathf
    {
        public static int RoundToInt(float f) => (int)Math.Round(f);
        public static int Max(int a, int b) => a > b ? a : b;
        public static float Max(float a, float b) => a > b ? a : b;
        public static int Min(int a, int b) => a < b ? a : b;
        public static float Min(float a, float b) => a < b ? a : b;
        public static int Clamp(int value, int min, int max)
        {
            if (value < min) value = min;
            else if (value > max) value = max;
            return value;
        }
        public static float Clamp(float value, float min, float max)
        {
            if (value < min) value = min;
            else if (value > max) value = max;
            return value;
        }
    }

    public static class Debug
    {
        public static int ErrorCount;
        public static readonly List<string> Errors = new List<string>();

        public static void Log(object message) { }
        public static void LogWarning(object message) { }
        public static void LogError(object message)
        {
            ErrorCount++;
            if (Errors.Count < 20) Errors.Add(message?.ToString());
        }
    }
}
