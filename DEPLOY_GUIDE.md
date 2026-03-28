# 🚀 VILLAIN × PHANTOM — Cloud Deploy Guide
## Phone pe Live — Koi PC nahi chahiye

---

## Total Time: ~15 minutes

---

## STEP 1 — GitHub Account Banao (Free)
👉 https://github.com → Sign Up (free)

---

## STEP 2 — New Repository Banao

1. GitHub pe login karo
2. **"New repository"** click karo (green button)
3. Name: `villain-phantom-ai`
4. **Public** select karo
5. **"Create repository"** click karo

---

## STEP 3 — Files Upload Karo

Repository page pe **"uploading an existing file"** link click karo

**Ye saare files upload karo** (is ZIP se):
```
app.py
requirements.txt
render.yaml
index.html
manifest.json
sw.js
icon-192.png
icon-512.png
```

**"Commit changes"** click karo → Done ✅

---

## STEP 4 — Render.com pe Deploy Karo

👉 https://render.com → **Sign Up with GitHub** (free)

1. Dashboard pe **"New +"** → **"Web Service"**
2. **"Connect a repository"** → `villain-phantom-ai` select karo
3. Settings:
   - **Name**: `villain-phantom-ai`
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Plan**: **Free** ✅
4. **"Create Web Service"** click karo

⏳ 3-5 minutes wait karo...

✅ Tumhara URL milega: `https://villain-phantom-ai.onrender.com`

---

## STEP 5 — Phone pe Install Karo

1. **Chrome** pe ye URL open karo: `https://villain-phantom-ai.onrender.com`
2. Chrome menu (⋮) → **"Add to Home Screen"**
3. **"Install"** tap karo

📱 **Done! App install ho gaya!**

---

## Angel One Credentials Add Karo (Live Trading ke liye)

Render Dashboard → villain-phantom-ai → **Environment** tab → **Add Environment Variable**:

| Key | Value |
|-----|-------|
| `ANGEL_API_KEY` | tumhara key |
| `ANGEL_CLIENT_ID` | A123456 |
| `ANGEL_PASSWORD` | password |
| `ANGEL_TOTP_SECRET` | secret key |

Save karo → Auto redeploy hoga → F&O live orders chalenge ✅

---

## Data Sources

| Feature | Source | Cost |
|---------|--------|------|
| Gold/Forex prices | Yahoo Finance | FREE |
| Nifty/BankNifty | Yahoo Finance | FREE |
| AI Signals | Backend compute | FREE |
| F&O Orders | Angel One API | FREE |
| Forex Orders | MT5 (Windows only) | FREE |

---

## ⚠️ Render Free Tier Limitation

Free tier pe app 15 minutes inactivity ke baad "sleep" ho jata hai.
Pehli request pe 30-60 seconds lag sakte hain (cold start).

**Solution**: UptimeRobot se ping karo (free):
👉 https://uptimerobot.com → New Monitor → HTTP → URL dalo → Every 5 min

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| App open nahi ho raha | 30 sec wait karo (cold start) |
| Prices nahi aa rahe | Normal — demo data dikhega, real prices 10s mein |
| Orders execute nahi | Angel credentials check karo in Render env vars |
| "Service unavailable" | Render dashboard mein logs dekho |
