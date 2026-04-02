using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace ReactionTest.Experiment
{
    public class AgencySurveyUI : MonoBehaviour
    {
        [SerializeField] private CanvasGroup root;
        [SerializeField] private List<Button> likertButtons = new List<Button>();
        [SerializeField] private Text promptText;  // 通常のUI Text

        private void Awake()
        {
            // 初期状態で非表示
            if (root != null)
            {
                Show(false);
            }
            else
            {
                Debug.LogWarning("AgencySurveyUI: root (CanvasGroup) is not assigned!");
            }
        }

        public IEnumerator AskAgency(Action<int> onAnswered)
        {
            Debug.Log("AgencySurveyUI: AskAgency called");
            
            if (root == null)
            {
                Debug.LogError("AgencySurveyUI: root (CanvasGroup) is null!");
                onAnswered?.Invoke(4); // デフォルト値を返す
                yield break;
            }
            
            if (likertButtons == null || likertButtons.Count != 7)
            {
                Debug.LogError($"AgencySurveyUI: likertButtons invalid (count={likertButtons?.Count ?? 0}, expected 7)");
                onAnswered?.Invoke(4);
                yield break;
            }

            bool answered = false;
            int answer = 4;

            if (promptText != null)
            {
                promptText.text = "主体感はどの程度ありましたか？ (1: まったくない - 7: 非常に強い)";
            }

            Debug.Log("AgencySurveyUI: Showing UI");
            Show(true);

            for (int i = 0; i < likertButtons.Count; i++)
            {
                int likertValue = i + 1;
                Button b = likertButtons[i];
                if (b == null)
                {
                    Debug.LogWarning($"AgencySurveyUI: likertButtons[{i}] is null");
                    continue;
                }

                b.onClick.RemoveAllListeners();
                b.onClick.AddListener(() =>
                {
                    answer = likertValue;
                    answered = true;
                    Debug.Log($"AgencySurveyUI: Button {likertValue} clicked");
                });
            }

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
            Debug.Log($"AgencySurveyUI: Show({visible}) - alpha={root.alpha}");
        }
    }
}
