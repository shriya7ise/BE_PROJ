# VIGILANCE ESG frontend (local clone)

Dark UI clone of the Lovable prototype with:

1. **Reasoning & Recommendation** panel on company detail (`/companies/:symbol`)
2. **AI Chat** sidebar tab (`/chat`) with optional company context

## Run

```bash
cd vigilance-frontend
npm install
npm run dev
```

Open http://localhost:5173

## Demo path

1. Overview → click a company in Entity Risk Index, **or** Companies → **Aptiv PLC (APTV)**
2. See Reasoning panel (score, tier, model P(risk), drivers, explanation, recommendation)
3. Click **Ask AI about APTV** → AI Chat with context
4. Ask e.g. “Why is risk critical?”

## Wire to real backend later

- `GET /api/companies/{symbol}/reasoning` → fill `getReasoning`
- `POST /api/chat` → replace `mockReply` in `AIChat.jsx`
