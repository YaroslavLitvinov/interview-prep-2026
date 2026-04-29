# 📚 Interview Prep Streamlit App

Interactive knowledge base for 2026 interview preparation with built-in Claude AI chat.

## Features

✅ **Knowledge Base Navigation**
- 6 specialized indexes (System Design, Technical Depth, Coding, Behavioral, Company Research)
- Beautiful markdown rendering
- Easy sidebar navigation
- Mobile-friendly UI

✅ **Interactive Chat**
- Ask questions about interview prep
- Claude AI responses (via local CLI)
- Chat history tracking
- Context-aware answers

✅ **Responsive Design**
- Works on laptop, tablet, phone
- Same WiFi network access
- Settings (font size, chat history)

## Quick Start

### 1. Install Dependencies
```bash
cd app/
pip install -r requirements.txt
```

### 2. Install Claude CLI
```bash
pip install anthropic
```

### 3. Run the App
```bash
streamlit run interview_prep_app.py
```

### 4. Access from Phone
App runs at:
- **Local**: http://localhost:8501
- **Network**: http://192.168.x.x:8501 (find your IP with `ifconfig`)

From phone on same WiFi:
1. Open browser
2. Type your computer's IP:8501
3. Browse knowledge base
4. Chat with Claude!

## Directory Structure

```
app/
├── interview_prep_app.py      # Main Streamlit app
├── requirements.txt           # Python dependencies
└── README.md                  # This file

../
├── Interview-Prep-INDEX.k.md  # Main entry point
└── index/                     # 6 specialized indexes
    ├── Grokking-the-System-Design-Interview.k.md
    ├── Technical-Depth-Index.k.md
    ├── Coding-Interview-Guide.k.md
    ├── Behavioral-Interview-Guide.k.md
    ├── Company-Research-Template.k.md
    └── Interview-Prep-Master-Index.k.md
```

## Usage

### From Phone
1. Connect to same WiFi as your computer
2. Open browser
3. Visit: http://[your-computer-ip]:8501
4. Browse knowledge base using sidebar navigation
5. Ask questions in chat interface

### From Desktop
```bash
cd app/
streamlit run interview_prep_app.py
# Opens at http://localhost:8501
```

## Features Explained

### 📖 Navigation (Sidebar)
- **Home**: Main entry point with overview
- **System Design**: 7-step framework + 3 case studies
- **Technical Depth**: 6 technical areas
- **Coding Interview**: LeetCode patterns + implementations
- **Behavioral**: STAR stories + culture fit
- **Company Research**: Template for company research
- **Master Navigation**: 4-dimensional navigation

### 💬 Chat
- Ask any interview prep question
- Get responses from Claude AI
- Chat history stored in session
- No internet connection needed (local Claude CLI)

### ⚙️ Settings
- Toggle chat history display
- Adjust font size
- Responsive to screen size

## Tips

💡 **Best Practices:**
- Use on phone while reading materials on laptop
- Take notes during chat conversations
- Review chat history to reinforce learning
- Ask follow-up questions to deepen understanding

🔌 **Network Setup:**
- Ensure phone and computer on same WiFi
- Use computer's local IP (not localhost) from phone
- Find IP: `ifconfig | grep "inet "`

⚡ **Performance:**
- First Claude response takes ~3 seconds (loading)
- Subsequent responses are faster
- Works smoothly on 4G/5G if on same network

## Troubleshooting

**"Claude CLI not found"**
```bash
pip install anthropic
```

**Can't access from phone**
- Check both devices on same WiFi
- Use full IP address (not localhost)
- Example: http://192.168.1.100:8501
- Check firewall settings

**App not responding**
- Check terminal for errors
- Restart: Ctrl+C then `streamlit run interview_prep_app.py`

## Development

### Adding New Features

1. **Custom Chat Commands**
   - Add slash commands (/quiz, /mock, etc.)
   - Implement in `ask_claude()` function

2. **Progress Tracking**
   - Save session state to file
   - Track which sections studied

3. **Mock Interviews**
   - Time-based system design challenges
   - Auto-generate coding problems

4. **Notes Taking**
   - Add note-taking sidebar
   - Export notes to markdown

## Future Enhancements

- [ ] Mock interview mode (45-min timer)
- [ ] Progress dashboard
- [ ] Note-taking feature
- [ ] Dark mode
- [ ] Multi-user support
- [ ] Export chat as PDF
- [ ] Voice input/output
- [ ] Spaced repetition quizzes

---

**Ready to prep?** Run `streamlit run interview_prep_app.py` and start from your couch! 🚀
