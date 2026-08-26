# AI detection for Word documents

This project analyzes .docx files and highlights likely AI-generated paragraphs.

Quick start

1. Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2. Set environment variables for the external API and optional OpenAI integration.

```powershell
$env:ANALYSIS_API_URL = 'https://your-provider.com/analyze'
$env:ANALYSIS_API_KEY = 'your-api-key'
$env:OPENAI_API_KEY = 'sk-...'
$env:MONGODB_URI = 'mongodb+srv://<db_username>:<db_password>@cluster0.sqpsljx.mongodb.net'
$env:MONGODB_DB = 'ai_plag_analyzer'
```

3. Install dependencies and run the backend server:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

> If the backend reports `Form data requires "python-multipart"`, install it with `pip install python-multipart` and rerun.

4. Run the frontend during development:

```powershell
cd frontend
npm install
npm run dev
```

5. Upload a `.docx` document through the frontend, choose either AI Detection or Plagiarism Detection, and inspect results.

6. If you only want to run the local analyzer without the external API, leave `ANALYSIS_API_URL` unset.

7. Subscription plans are shown in the frontend. Current options:
   - Free: 119 words
   - Basic: 2999 words for ₹599/-
   - Premium: 7999 words for ₹1499/-
   - Premium Pro: 10000 words for ₹1999/-

   Pay via UPI: `gogreensavepaper@ibl`
   Terms and conditions apply. No profit business.

8. Run the analyzer:

```powershell
python analyze_docx.py input.docx --output report.html --json results.json
```

If no OpenAI key or package is present, the script uses a lightweight heuristic fallback.

Outputs
- `report.html`: colored HTML report with paragraph-level scores
- `results.json`: structured JSON with scores and reasons
