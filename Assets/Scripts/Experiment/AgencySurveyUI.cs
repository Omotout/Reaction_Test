using System;
using System.Collections;
#if UNITY_EDITOR
using UnityEditor;
#endif
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.UI;

namespace ReactionTest.Experiment
{
    // ========================================================================
    // V3: 2値（Yes/No）によるAgency評価UI
    // ========================================================================

    public class AgencySurveyUI : MonoBehaviour
    {
        [SerializeField] private CanvasGroup root;
        [SerializeField] private Button yesButton;
        [SerializeField] private Button noButton;
        [SerializeField] private Text promptText;
        [SerializeField] private bool showInEditor = false;

        [Tooltip("回答待ちのタイムアウト（秒）。UI不具合や入力不能時の無限待機を防ぐ。0 または負で無効。")]
        [SerializeField] private float timeoutSeconds = 60f;

        // 緊急停止 / タイムアウト時に true。呼び出し側（Orchestrator）で参照する。
        private bool _isAborted = false;
        public bool IsAborted => _isAborted;
        public void ResetAbort() => _isAborted = false;

#if UNITY_EDITOR
        private bool _editorVisibilityApplyQueued;
#endif

        private void Awake()
        {
            HideImmediate();
        }

        private void OnValidate()
        {
#if UNITY_EDITOR
            if (!Application.isPlaying)
            {
                QueueApplyEditorVisibility();
            }
#endif
        }

        private void Reset()
        {
            root = GetComponent<CanvasGroup>();
#if UNITY_EDITOR
            if (!Application.isPlaying)
            {
                QueueApplyEditorVisibility();
                return;
            }
#endif
            HideImmediate();
        }

        public IEnumerator AskAgency(Action<bool> onAnswered)
        {
            Debug.Log("AgencySurveyUI: AskAgency called");

            if (root == null || yesButton == null || noButton == null)
            {
                Debug.LogError("AgencySurveyUI: Invalid setup. Root, yesButton, or noButton is missing.");
                onAnswered?.Invoke(true); // default
                yield break;
            }

            bool answered = false;
            bool answer = false;

            if (promptText != null)
            {
                promptText.text = "自分でボタンを押した感覚がありましたか？";
            }

            yesButton.onClick.RemoveAllListeners();
            noButton.onClick.RemoveAllListeners();

            yesButton.onClick.AddListener(() => { answer = true; answered = true; });
            noButton.onClick.AddListener(() => { answer = false; answered = true; });

            Show(true);

            var keyboard = Keyboard.current;
            float elapsed = 0f;

            while (!answered)
            {
                // 緊急停止: Escapeキー（実験全体の abort ポリシーと整合）
                if (keyboard != null && keyboard.escapeKey.wasPressedThisFrame)
                {
                    _isAborted = true;
                    Debug.LogError("AgencySurveyUI: ABORT requested (Escape key) during Agency survey");
                    break;
                }

                // タイムアウト: UI不具合や入力デバイス不通時に無限待機しないよう打ち切る
                if (timeoutSeconds > 0f)
                {
                    elapsed += Time.unscaledDeltaTime;
                    if (elapsed >= timeoutSeconds)
                    {
                        _isAborted = true;
                        Debug.LogError($"AgencySurveyUI: TIMEOUT after {timeoutSeconds:F1}s with no response");
                        break;
                    }
                }

                yield return null;
            }

            Show(false);

            if (_isAborted)
            {
                // abort 時は既定値（No = false）を返すが、Orchestrator は IsAborted を見て処理する
                onAnswered?.Invoke(false);
            }
            else
            {
                Debug.Log($"AgencySurveyUI: Answer received: {answer}");
                onAnswered?.Invoke(answer);
            }
        }

        private void Show(bool visible)
        {
            if (root == null) return;

            root.alpha = visible ? 1f : 0f;
            root.interactable = visible;
            root.blocksRaycasts = visible;
        }

        private void HideImmediate()
        {
            if (root == null) return;

            root.alpha = 0f;
            root.interactable = false;
            root.blocksRaycasts = false;

#if UNITY_EDITOR
            if (!Application.isPlaying)
            {
                EditorUtility.SetDirty(root);
            }
#endif
        }

        private void ApplyEditorVisibility()
        {
            if (root == null) return;

            if (showInEditor)
            {
                root.alpha = 1f;
                root.interactable = true;
                root.blocksRaycasts = true;
            }
            else
            {
                root.alpha = 0f;
                root.interactable = false;
                root.blocksRaycasts = false;
            }

#if UNITY_EDITOR
            EditorUtility.SetDirty(root);
#endif
        }

#if UNITY_EDITOR
        private void QueueApplyEditorVisibility()
        {
            if (_editorVisibilityApplyQueued) return;

            _editorVisibilityApplyQueued = true;
            EditorApplication.delayCall += ApplyEditorVisibilityDelayed;
        }

        private void ApplyEditorVisibilityDelayed()
        {
            _editorVisibilityApplyQueued = false;

            if (this == null || Application.isPlaying) return;

            ApplyEditorVisibility();
        }
#endif
    }
}
