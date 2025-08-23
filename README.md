# MyAnswerChecker 🎓🤖

> **"Study with AI, not alone."**
> An Anki add-on that transforms your reviews into an interactive AI-powered study session.

![Anki](https://img.shields.io/badge/Anki-2.1.55+-blue?logo=ankidroid)
![Python](https://img.shields.io/badge/Python-3.9+-yellow?logo=python)
![License](https://img.shields.io/github/license/Junibabng/MyAnswerChecker)

---

## ✨ Key Highlights

### 1. 📚 Study *with* AI

* Your **Anki card** appears in a **chat bubble**.
* Type your answer → AI evaluates it semantically (not just keyword matching).
* Continue chatting with AI about the card to **ask questions and deepen understanding**.

### 2. 🎯 Automatic Difficulty Rating

* After you submit your answer, AI:

  * Judges accuracy & response time
  * Suggests a difficulty rating *(Again / Hard / Good / Easy)*
* You can:

  * **Accept AI’s rating** → Press **Enter** with empty chat box → auto-advance to next card
  * **Disagree** → Click your own rating button

👉 This creates a smooth flow: *Answer → Feedback → Next card* 🚀

---

## 🎥 Demo (Video & Screenshots)

### Demonstration Video

📹 


https://github.com/user-attachments/assets/c1b3f63e-c374-45fa-be0a-dd17881fd12d


### Screenshots

* Answer evaluation interface:
  `![Answer Check](bandicam.2025-08-19-14-38-21-125.png)`
* Conversation mode:
  `![Conversation](bandicam.2025-08-19-14-38-11-031.png)`
* Difficulty settings UI:
  `![Difficulty Settings](bandicam.2025-08-19-14-38-25-091.png)`
* General settings (temperature, prompt):
  `![General Settings](bandicam.2025-08-19-14-38-29-305.png)`

---

## ⚡ Features

* **Interactive Answer Evaluation**: Chat-like interface with AI feedback.
* **Comprehensive Feedback**: Correct answer, accuracy check, response-time evaluation, suggested difficulty.
* **AI-Powered Conversations**: Ask follow-up questions about the card’s content.
* **Streamlined Flow**: Press Enter to accept AI’s suggestion and move on.
* **Flexible Provider Support**:

  * OpenAI GPT models (custom Base URL supported)
  * Google Gemini models
* **Customizable Settings**:

  * Temperature (creativity of AI)
  * System prompt (tone & evaluation style)
  * Time thresholds for difficulty rating

---

## 🛠️ Installation

1. Download the latest release from [AnkiWeb](https://ankiweb.net/) or GitHub Releases.
2. In Anki: **Tools → Add-ons → Install from file…**
3. Select the `.ankiaddon` file.
4. Restart Anki.

---

## ⚙️ Settings Overview

### API Settings

* **Provider**: Choose OpenAI-compatible or Gemini.
* **Custom Base URL**: Use alternative API endpoints if needed.
* **API Key**: Enter securely.

### Difficulty Settings

* Configure time thresholds (e.g. Easy <5s, Good 5–30s, Hard ≥30s).
* AI uses both **semantic accuracy + timing** for final judgment.

### General Settings

* **Temperature**: Control creativity (0.0 = strict, 1.0 = creative).
* **System Prompt**: Adjust how AI explains and evaluates answers.

---

## 🔒 Privacy & Security

* No answer data is stored permanently.
* API keys stored securely in Anki config.
* All traffic encrypted via HTTPS.
* Local pre-processing before sending to AI.

---

## 🤝 Contributing

* Issues, feature requests, and PRs are welcome!

---

## 📜 License

MIT License © 2025 Junibabng
