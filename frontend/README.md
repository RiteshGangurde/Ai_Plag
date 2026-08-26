# Frontend (React + Vite)

Run frontend locally:

```powershell
cd frontend
npm install
npm run dev
```

The app expects a backend endpoint at `/analyze` that accepts a `multipart/form-data` POST with a `file` field and returns JSON. You can ask me to scaffold a small Flask/FastAPI server that wraps `analyze_docx.py`.
