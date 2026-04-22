using System;
using System.Collections;
using UnityEngine;
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

        private void Awake()
        {
            if (root != null)
            {
                Show(false);
            }
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

            while (!answered)
            {
                yield return null;
            }

            Debug.Log($"AgencySurveyUI: Answer received: {answer}");
            Show(false);
            onAnswered?.Invoke(answer);
        }

        private void Show(bool visible)
        {
            if (root == null) return;
            
            root.alpha = visible ? 1f : 0f;
            root.interactable = visible;
            root.blocksRaycasts = visible;
        }
    }
}
