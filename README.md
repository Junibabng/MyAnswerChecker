# MyAnswerChecker - Anki Answer Evaluation Add-on

An intelligent Anki add-on that evaluates your answers using LLM (Large Language Model) technology, providing semantic understanding and personalized feedback.

## Features

### Core Functionality
- **Semantic Answer Evaluation**: Evaluates answers based on meaning rather than exact matches
- **Multiple LLM Support**: 
  - OpenAI (GPT models)
  - Google Gemini
- **Intelligent Difficulty Rating**: Automatically suggests difficulty ratings (Again, Hard, Good, Easy) based on:
  - Answer accuracy
  - Response time
  - Understanding level
- **Real-time Feedback**: Provides immediate feedback on your answers with explanations

### Advanced Features
- **Conversation Context**: Maintains context of your study session for more relevant feedback
- **Multiple Card Type Support**:
  - Basic cards
  - Cloze deletion cards
  - Support for HTML content
- **Customizable Settings**:
  - LLM provider selection
  - API configuration
  - Response time thresholds
  - System prompts
  - Language preferences

### Technical Improvements
- Complete type hint coverage for better code reliability
- Robust error handling with detailed logging
- ThreadPoolExecutor for improved performance
- Comprehensive API response validation
- Automatic retries with exponential backoff

## Installation

1. Download the add-on from AnkiWeb (Add-on code: XXXXX)
2. In Anki, go to Tools → Add-ons → Install from file
3. Select the downloaded file
4. Restart Anki

## Configuration

### Initial Setup
1. Open Anki
2. Go to Tools → Answer Checker → Settings
3. Configure your preferred LLM provider:
   - For OpenAI: Enter your API key and select model
   - For Gemini: Enter your API key and select model
4. Adjust other settings as needed:
   - Response time thresholds
   - System prompt
   - Debug logging options

### Time Thresholds
Default thresholds for difficulty ratings:
- Easy: < 5 seconds
- Good: 5-30 seconds
- Hard: ≥ 30 seconds
- Auto-Again: > 60 seconds

## Usage

1. Start reviewing cards as normal
2. Your answer will be automatically evaluated when you type it
3. The add-on will:
   - Analyze your answer semantically
   - Consider your response time
   - Provide detailed feedback
   - Suggest a difficulty rating
4. You can:
   - Follow the suggested rating
   - Choose your own rating
   - Ask follow-up questions
   - View detailed explanations

## Features in Detail

### Semantic Evaluation
- Understands meaning beyond exact matches
- Accepts valid synonyms and alternative expressions
- Considers context and language variations
- Handles informal and regional language differences

### Answer Processing
- Removes HTML formatting for clean text comparison
- Handles special card formats (e.g., cloze deletions)
- Maintains conversation history for context
- Provides constructive feedback

### Error Handling
- Graceful handling of API issues
- Clear error messages with helpful suggestions
- Automatic retry mechanism for transient errors
- Detailed logging for troubleshooting

## Requirements

- Anki 2.1.55 or later
- Python 3.9 or later
- Internet connection for LLM API access
- Valid API key for chosen provider

## Privacy & Security

- No answer data is stored permanently
- API keys are stored securely in Anki's configuration
- All communication is encrypted (HTTPS)
- Local processing where possible

## Troubleshooting

Common issues and solutions:
1. **API Connection Issues**
   - Check internet connection
   - Verify API key
   - Ensure correct base URL
   
2. **Answer Evaluation Issues**
   - Check card formatting
   - Verify answer field content
   - Review system prompt settings

3. **Performance Issues**
   - Check debug logs
   - Adjust time thresholds
   - Verify system resources

## Support

- GitHub Issues: [Link to repository]
- AnkiWeb: [Link to addon page]
- Documentation: [Link to detailed docs]

## Contributing

Contributions are welcome! Please see our contributing guidelines for more information.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Third-Party Licenses
This add-on vendors minimal dependencies under `libs/` and redistributes them under their original licenses:
- bs4 (BeautifulSoup4) — MIT
- soupsieve — MIT
- requests — Apache-2.0
- urllib3 — MIT
- certifi — MPL-2.0
- charset_normalizer — MIT
- idna — BSD-3-Clause

Notes:
- We do not modify these packages; licenses and notices are preserved.
- For MPL-2.0 (certifi), if modified, the modified files would be provided under MPL-2.0.

## Acknowledgments

- Anki for the amazing flashcard platform
- OpenAI and Google for their LLM APIs
- The Anki add-on community for inspiration and support
