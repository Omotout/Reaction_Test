using System.Globalization;

namespace ReactionTest.Experiment
{
    /// <summary>Arduino→Unity のトライアル結果（RTはms、µsから変換済み）。</summary>
    public struct TrialResult
    {
        public int Id;                 // 送信したTRIALのシーケンスID（エコーバック）
        public UserAction TouchedSide; // Left/Right、タイムアウト時 None
        public float RtMs;             // タイムアウト時 -1
        public int Peak;
        public bool EmsFired;
        public bool TimedOut;
    }

    /// <summary>Arduino→Unity の EMS_to_Touch 計測結果（msに変換済み）。</summary>
    public struct EmsLatencyResult
    {
        public int Id;                 // 送信したEMSLATのシーケンスID（エコーバック）
        public UserAction Side;
        public float LatencyMs;        // タイムアウト時 -1
        public bool TimedOut;
    }

    /// <summary>
    /// Unity↔Arduino 行ベース・プロトコルの正本（コマンド整形＋応答パース）。純粋ロジック・UnityEngine非依存。
    /// Arduinoファームウェア(integrated_full系)はこの文字列仕様に整合させること。
    /// 時間はArduino側でµs、Unity側でms(float)に変換する。
    /// ピン対応: LED赤=D11, LED緑(YG)=D12, タッチ右=D9/左=D10, EMS左=D3,4/右=D5,6。
    ///
    /// シーケンスID: TRIAL/EMSLAT に単調増加の id を載せ、Arduinoは結果(TRIAL_RESULT/EMSLAT_RESULT)で
    /// 同じ id をエコーする。Unityは期待idと一致する結果のみ採用し、タイムアウト後に届く遅延結果
    /// （前試行の応答）を破棄して試行ずれを防ぐ。
    ///
    /// コマンド表記の規約:
    ///   - integrated_full.ino に既存のコマンドはコロン式のまま踏襲（LED:OFF / EMS:R / RESET / STATUS）。
    ///   - 本フレームワークで新設する可変長コマンドはカンマ区切り（TRIAL / EMSLAT / THR / EMSCFG）。
    /// </summary>
    public static class ArduinoProtocol
    {
        public const string LedOff = "LED:OFF";
        public const string Reset  = "RESET";
        public const string Status = "STATUS";

        /// <summary>左右を1文字に。None はプログラミングエラーとして例外（黙って"R"に倒さない）。</summary>
        public static string Side(UserAction s)
        {
            if (s == UserAction.Left) return "L";
            if (s == UserAction.Right) return "R";
            throw new System.ArgumentOutOfRangeException(nameof(s), s, "Side は Left/Right のみ。");
        }

        public static string Color(StimColor c) => c == StimColor.Red ? "R" : "G";

        // ---- Unity → Arduino ----
        public static string FormatTrial(int id, StimColor led, UserAction resp, UserAction emsSide, int emsDelayUs)
        {
            string ems = (emsSide == UserAction.None) ? "N" : Side(emsSide);
            return string.Format(CultureInfo.InvariantCulture,
                "TRIAL,{0},{1},{2},{3},{4}", id, Color(led), Side(resp), ems, emsDelayUs);
        }

        public static string FormatEmsLatency(int id, UserAction side)
            => string.Format(CultureInfo.InvariantCulture, "EMSLAT,{0},{1}", id, Side(side));

        public static string FormatThreshold(UserAction side, int value)
            => string.Format(CultureInfo.InvariantCulture, "THR,{0},{1}", Side(side), value);

        public static string FormatEmsConfig(int widthUs, int count, int burst, int intervalUs)
            => string.Format(CultureInfo.InvariantCulture, "EMSCFG,{0},{1},{2},{3}", widthUs, count, burst, intervalUs);

        public static string FormatEmsManual(UserAction side) => "EMS:" + Side(side);

        // ---- Arduino → Unity ----
        // TRIAL_RESULT,<id>,<touchedSide>,<rtUs>,<peak>,<emsFired>
        public static bool TryParseTrialResult(string line, out TrialResult result)
        {
            result = default;
            if (string.IsNullOrEmpty(line)) return false;
            string[] p = line.Trim().Split(',');
            if (p.Length < 6 || p[0] != "TRIAL_RESULT") return false;

            if (!int.TryParse(p[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out int id))
                return false;
            result.Id = id;

            if (p[2] == "NONE")
            {
                // タイムアウト時は rtUs(p[3]) を参照しない（TimedOut が正本のシグナル）。
                result.TouchedSide = UserAction.None;
                result.RtMs = -1f;
                result.TimedOut = true;
            }
            else if (p[2] == "R" || p[2] == "L")
            {
                result.TouchedSide = (p[2] == "R") ? UserAction.Right : UserAction.Left;
                if (!long.TryParse(p[3], NumberStyles.Integer, CultureInfo.InvariantCulture, out long rtUs))
                    return false;
                result.RtMs = rtUs / 1000f;
                result.TimedOut = false;
            }
            else return false;

            if (!int.TryParse(p[4], NumberStyles.Integer, CultureInfo.InvariantCulture, out int peak))
                return false;
            result.Peak = peak;
            result.EmsFired = (p[5] == "1"); // "1"=発火、それ以外は未発火（厳密一致）
            return true;
        }

        // EMSLAT_RESULT,<id>,<side>,<latencyUs>
        public static bool TryParseEmsLatency(string line, out EmsLatencyResult result)
        {
            result = default;
            if (string.IsNullOrEmpty(line)) return false;
            string[] p = line.Trim().Split(',');
            if (p.Length < 4 || p[0] != "EMSLAT_RESULT") return false;

            if (!int.TryParse(p[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out int id))
                return false;
            result.Id = id;

            if (p[2] != "R" && p[2] != "L") return false;
            result.Side = (p[2] == "R") ? UserAction.Right : UserAction.Left;

            if (!long.TryParse(p[3], NumberStyles.Integer, CultureInfo.InvariantCulture, out long us))
                return false;
            if (us < 0) { result.LatencyMs = -1f; result.TimedOut = true; }
            else { result.LatencyMs = us / 1000f; result.TimedOut = false; }
            return true;
        }
    }
}
