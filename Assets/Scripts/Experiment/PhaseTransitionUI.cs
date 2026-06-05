using System.Collections;
#if UNITY_EDITOR
using UnityEditor;
#endif
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.InputSystem;

namespace ReactionTest.Experiment
{
    /// <summary>
    /// フェーズ間の移行UI
    /// テキスト表示とスペースキー待機
    /// </summary>
    public class PhaseTransitionUI : MonoBehaviour
    {
        [SerializeField] private CanvasGroup root;
        [SerializeField] private Text phaseNameText;
        [SerializeField] private Text instructionText;
        [SerializeField] private Text pressSpaceText;
        [SerializeField] private bool showInEditor = false;

#if UNITY_EDITOR
        private bool _editorVisibilityApplyQueued;
#endif

        private void Awake()
        {
            ConfigureTextLayout();
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

        /// <summary>
        /// フェーズ移行画面を表示し、スペースキーが押されるまで待機
        /// </summary>
        public IEnumerator ShowPhaseAndWait(string phaseName, string instruction)
        {
            if (root == null)
            {
                Debug.LogWarning("PhaseTransitionUI: root is not assigned, skipping.");
                yield break;
            }

            ConfigureTextLayout();

            if (phaseNameText != null)
            {
                phaseNameText.text = phaseName;
            }

            if (instructionText != null)
            {
                instructionText.text = instruction;
            }

            if (pressSpaceText != null)
            {
                pressSpaceText.text = "スペースキーを押して開始";
            }

            Show(true);

            // スペースキーが押されるまで待機
            var keyboard = Keyboard.current;
            while (true)
            {
                if (keyboard != null && keyboard.spaceKey.wasPressedThisFrame)
                {
                    break;
                }
                yield return null;
            }

            Show(false);
            
            // 少し待機してから開始
            yield return new WaitForSeconds(0.5f);
        }

        private void ConfigureTextLayout()
        {
            ConfigureText(phaseNameText, new Vector2(0f, 130f), new Vector2(900f, 80f), 36);
            ConfigureText(instructionText, new Vector2(0f, 15f), new Vector2(900f, 160f), 26);
            ConfigureText(pressSpaceText, new Vector2(0f, -135f), new Vector2(900f, 50f), 22);
        }

        private static void ConfigureText(Text text, Vector2 position, Vector2 size, int fontSize)
        {
            if (text == null) return;

            var rect = text.rectTransform;
            rect.anchorMin = new Vector2(0.5f, 0.5f);
            rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = size;

            text.alignment = TextAnchor.MiddleCenter;
            text.fontSize = fontSize;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Overflow;
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
