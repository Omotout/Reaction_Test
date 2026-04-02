using System.Collections;
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

        private void Awake()
        {
            if (root != null)
            {
                Show(false);
            }
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

        private void Show(bool visible)
        {
            root.alpha = visible ? 1f : 0f;
            root.interactable = visible;
            root.blocksRaycasts = visible;
        }
    }
}
