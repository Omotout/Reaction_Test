using System;
using System.Collections.Concurrent;
using System.IO.Ports;
using System.Threading;
using UnityEngine;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// Unity↔Arduino の単一シリアル所有者（双方向）。送信は ArduinoProtocol で整形し TX スレッドで書き出す。
    /// 受信は RX スレッドで行単位に読み、メインスレッドの Update() で ArduinoProtocol によりパースして
    /// イベント通知する。時間臨界パス（LED点灯→EMS発火→タッチ→RT）は Arduino 側が実行し、Unity は結果のみ受け取る。
    /// 接続失敗時はシミュレーションモード（送信はログのみ）。
    /// </summary>
    public class ArduinoLink : MonoBehaviour
    {
        [Header("Serial")]
        [SerializeField] private string portName = "COM5";
        [SerializeField] private int baudRate = 115200;
        [SerializeField] private int readTimeoutMs = 50;

        private SerialPort _port;
        private Thread _txThread;
        private Thread _rxThread;
        private volatile bool _running;
        private readonly ConcurrentQueue<string> _txQueue = new ConcurrentQueue<string>();
        private readonly ConcurrentQueue<string> _rxQueue = new ConcurrentQueue<string>();

        private volatile bool _isConnected;
        public bool IsConnected => _isConnected;

        // メインスレッドで購読する受信イベント（Update から発火）
        public event Action<TrialResult> OnTrialResult;
        public event Action<EmsLatencyResult> OnEmsLatencyResult;
        public event Action<string> OnOtherLine;

        /// <summary>ポート名/ボーレートを上書きする。必ず Start() より前に呼ぶこと（開いた後は無効）。</summary>
        public void Configure(string port, int baud)
        {
            portName = port;
            baudRate = baud;
        }

        private void Start()
        {
            OpenPort();
        }

        private void OpenPort()
        {
            try
            {
                _port = new SerialPort(portName, baudRate);
                _port.ReadTimeout = readTimeoutMs;
                _port.WriteTimeout = 1000; // Arduino無応答/バッファ詰まり時の TX 無限ハングを防ぐ
                _port.NewLine = "\n";
                _port.Open();
                _isConnected = true;
                _running = true;

                _txThread = new Thread(TxWorker) { IsBackground = true };
                _rxThread = new Thread(RxWorker) { IsBackground = true };
                _txThread.Start();
                _rxThread.Start();
                Debug.Log($"ArduinoLink: connected {portName}@{baudRate}");
            }
            catch (Exception e)
            {
                _isConnected = false;
                Debug.LogWarning($"ArduinoLink: not connected (simulation mode) - {e.Message}");
            }
        }

        private void Update()
        {
            while (_rxQueue.TryDequeue(out string line))
            {
                Dispatch(line);
            }
        }

        private void Dispatch(string line)
        {
            if (string.IsNullOrEmpty(line)) return;

            if (ArduinoProtocol.TryParseTrialResult(line, out var trial))
            {
                OnTrialResult?.Invoke(trial);
            }
            else if (ArduinoProtocol.TryParseEmsLatency(line, out var lat))
            {
                OnEmsLatencyResult?.Invoke(lat);
            }
            else
            {
                OnOtherLine?.Invoke(line);
            }
        }

        // ---- 送信API ----
        public void SendTrial(StimColor led, UserAction resp, UserAction emsSide, int emsDelayUs)
            => Enqueue(ArduinoProtocol.FormatTrial(led, resp, emsSide, emsDelayUs));

        public void SendEmsLatency(UserAction side) => Enqueue(ArduinoProtocol.FormatEmsLatency(side));
        public void SendThreshold(UserAction side, int value) => Enqueue(ArduinoProtocol.FormatThreshold(side, value));
        public void SendEmsConfig(int width, int count, int burst, int interval)
            => Enqueue(ArduinoProtocol.FormatEmsConfig(width, count, burst, interval));
        public void SendEmsManual(UserAction side) => Enqueue(ArduinoProtocol.FormatEmsManual(side));
        public void SendLedOff() => Enqueue(ArduinoProtocol.LedOff);
        public void SendReset() => Enqueue(ArduinoProtocol.Reset);
        public void SendStatus() => Enqueue(ArduinoProtocol.Status);

        private void Enqueue(string command)
        {
            if (!_isConnected)
            {
                Debug.Log($"[ArduinoLink sim] TX: {command}");
                return;
            }
            _txQueue.Enqueue(command);
        }

        private void TxWorker()
        {
            while (_running)
            {
                if (_txQueue.TryDequeue(out string cmd))
                {
                    try { if (_port != null && _port.IsOpen) _port.WriteLine(cmd); }
                    catch (Exception e) { Debug.LogWarning($"ArduinoLink TX error: {e.Message}"); }
                }
                else
                {
                    Thread.Sleep(1);
                }
            }
        }

        private void RxWorker()
        {
            while (_running)
            {
                try
                {
                    string line = _port.ReadLine();
                    if (!string.IsNullOrEmpty(line)) _rxQueue.Enqueue(line.Trim());
                }
                catch (TimeoutException) { /* 通常: 読み取りタイムアウトは無視 */ }
                catch (Exception e)
                {
                    // Cleanup() の port.Close() が ReadLine 実行中に割り込むと例外になるが、
                    // シャットダウン中(_running==false)は想定内なのでログを抑制する。
                    if (_running) Debug.LogWarning($"ArduinoLink RX error: {e.Message}");
                    Thread.Sleep(5);
                }
            }
        }

        private void OnDestroy() => Cleanup();
        private void OnApplicationQuit() => Cleanup();

        private void Cleanup()
        {
            _running = false;
            try { _txThread?.Join(200); } catch { }
            try { _rxThread?.Join(200); } catch { }
            if (_port != null && _port.IsOpen)
            {
                try { _port.Close(); } catch { }
            }
            _isConnected = false;
        }
    }
}
