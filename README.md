# AI Answer Checker for Anki

An advanced Anki plugin that leverages AI to provide intelligent feedback on your answers, creating a more interactive and effective learning experience. Simply provide your AI API key, and the plugin will handle the rest.

## Demonstration

https://github.com/user-attachments/assets/fb3d238e-e200-42de-9a8d-2a03032c2646

## Features

- **Interactive Answer Evaluation:** Your card's front appears in a chat bubble, and you can submit your answer for an AI-powered assessment.
- **Comprehensive Feedback:** The AI provides the correct answer, evaluates your response, assesses your answering speed, and suggests a difficulty rating (`Again`, `Hard`, `Good`, `Easy`).
- **AI-Powered Conversations:** Engage in a follow-up conversation with the AI about the card's content to deepen your understanding.
- **Streamlined Review Process:** Simply press `Enter` to accept the AI's recommended rating and seamlessly move to the next card.
- **Flexible AI Provider Support:** Choose between OpenAI-compatible providers (with the ability to set a custom Base URL) and Google's Gemini.
- **Customizable Settings:** Fine-tune the AI's behavior by adjusting the temperature, editing the system prompt, and setting your own time-based difficulty thresholds.

## How to Use

1.  The front of the card is displayed in a message bubble within the "My Answer Checker" interface.
2.  Type your answer for the back of the card and press `Enter` or click the **Send** button.
3.  The AI will automatically provide a detailed evaluation, including:
    - The correct answer.
    - An assessment of your answer's accuracy.
    - Feedback on your response time.
    - A recommended review difficulty rating (`Again` / `Hard` / `Good` / `Easy`).
4.  From here, you have two options:
    - **3-1. Start a Conversation:** Type anything into the chat box to ask the AI follow-up questions about the card's topic.
    - **3-2. Proceed to Next Card:** With the chat box empty, simply press `Enter` again. This will accept the AI's recommended difficulty rating and automatically move to the next card.

## Plugin Settings

You can customize the plugin's behavior through the settings menu to better suit your study style and preferences.

### API Settings

Here, you can configure the AI provider you wish to use. You must obtain your own API key from your chosen provider.

-   **Provider Choice:** Select either an OpenAI-compatible provider or the Gemini provider.
-   **Custom Base URL:** For OpenAI-compatible options, you can modify the Base URL to use other compatible services.
-   **API Key:** Securely enter your personal API key.


![bandicam 2025-08-19 14-38-21-125](https://github.com/user-attachments/assets/8b8d95c2-c103-41b5-97f9-e2e7cfedd53e)
![bandicam 2025-08-19 14-38-11-031](https://github.com/user-attachments/assets/ce31cd1f-62e8-48ab-996e-4e5fcb3f59cc)

### Difficulty Settings

This tab allows you to define the response time thresholds (in seconds) for the `Easy`, `Good`, and `Hard` ratings. Since typing speed and card complexity vary from person to person, you are encouraged to adjust these settings to find what works best for you.

![bandicam 2025-08-19 14-38-25-091](https://github.com/user-attachments/assets/ab343d80-2905-4ddf-9a29-b6500c7242d7)

### General Settings

This menu provides options to control the AI's personality and response generation.

-   **Temperature:** Adjust the AI's creativity by setting a value between `0.0` and `1.0`. Lower values result in more deterministic responses, while higher values lead to more varied and creative outputs.
-   **System Prompt:** Modify the system prompt to guide the AI's behavior, tone, and the framework it uses for evaluating your answers.
   
![bandicam 2025-08-19 14-38-29-305](https://github.com/user-attachments/assets/b9d59ea0-96b8-41ac-ab5e-e699fa956969)
