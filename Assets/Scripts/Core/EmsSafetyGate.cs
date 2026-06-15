namespace ReactionTest.Experiment
{
    /// <summary>
    /// EMS発火の安全ゲート（純粋ロジック・UnityEngine非依存・テスト容易）。
    /// 不応期・1セッション最大発火回数・緊急停止を判定する。時刻はミリ秒値を呼び出し側から注入する
    /// （Stopwatch等の実時間源はMonoBehaviour側が保持し、ここは単調増加のms値だけを受け取る）。
    /// </summary>
    public class EmsSafetyGate
    {
        public enum Result
        {
            Allowed,
            EmergencyStopped,
            LimitReached,
            Refractory
        }

        public int RefractoryPeriodMs { get; set; }
        public int MaxFiresPerSession { get; set; }

        public bool EmergencyStopped { get; private set; }
        public int FireCount { get; private set; }

        private long _lastFireMs;
        private bool _hasFired;

        public EmsSafetyGate(int refractoryPeriodMs, int maxFiresPerSession)
        {
            RefractoryPeriodMs = refractoryPeriodMs;
            MaxFiresPerSession = maxFiresPerSession;
        }

        /// <summary>
        /// 発火可否を判定する。Allowed のときのみ内部状態（発火時刻・カウント）を更新する。
        /// 緊急停止 &gt; 上限 &gt; 不応期 の順で判定（最も重大な拒否理由を返す）。
        /// </summary>
        public Result TryFire(long nowMs)
        {
            if (EmergencyStopped) return Result.EmergencyStopped;
            if (FireCount >= MaxFiresPerSession) return Result.LimitReached;
            if (_hasFired && (nowMs - _lastFireMs) < RefractoryPeriodMs) return Result.Refractory;

            _lastFireMs = nowMs;
            _hasFired = true;
            FireCount++;
            return Result.Allowed;
        }

        /// <summary>緊急停止（ラッチ式：以後すべての発火を恒久的に拒否）。</summary>
        public void EmergencyStop() => EmergencyStopped = true;
    }
}
