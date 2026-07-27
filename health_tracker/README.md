# Health Tracking System (Working Prototype)

Built from the project proposal: registration, personal health data tracking,
central storage, alerts/notifications, and personalized insights.

## What's implemented vs. simulated

| Proposal component | This build |
|---|---|
| Mobile application | ✅ Responsive web app (works on phone/laptop browser) |
| Cloud storage & database | ✅ Local database (SQLite) — swap for MySQL/PostgreSQL for real cloud use |
| Data processing & analytics | ✅ Trend charts + rule-based insights |
| Real-time notifications & alerts | ✅ Auto-generated when a reading is out of healthy range |
| Wearable devices | ⚠️ Simulated — you enter readings manually; a real device would POST to `/entry/new` instead |
| Healthcare provider integration | ⚠️ Not built — would need a provider-facing login role and consent-sharing, out of scope for a laptop prototype |

## Requirements

- Python 3.9+ (you have this if `python3 --version` works)
- pip

## Setup (one-time)

Open a terminal in this folder and run:

```bash
pip install flask
```

(If `pip` isn't recognized, try `pip3` instead.)

## Run it

```bash
python3 app.py
```

You'll see:
```
Health Tracking System running at http://127.0.0.1:5000
```

Open that address in your browser. The first run auto-creates `health_tracker.db` in this folder — that's your database, no setup needed.

## Using it

1. **Register** an account (name, email, password).
2. **Log Entry** — enter steps, heart rate, blood pressure, sleep, weight, calories for a day.
3. **Dashboard** — see your latest stats, active health alerts (e.g. high blood pressure, low sleep), personalized insights, and trend charts.
4. **History** — full table of everything you've logged.

## Notes for your project report

- Alert thresholds (in `app.py`, function `evaluate_entry`) are based on common clinical rules of thumb (BP ≥140/90 = high, heart rate >100 or <50 bpm flagged, etc.) — cite real clinical guidelines (e.g. WHO/AHA) in your report if you use these numbers.
- The database is SQLite for simplicity; for the "cloud storage" requirement in your proposal, you'd point this at a hosted MySQL/PostgreSQL instance instead (a few line change in `get_db()`).
- To simulate a wearable device pushing data automatically instead of manual entry, a device/script could POST the same fields to `/entry/new` on a timer.

## File structure

```
health_tracker/
├── app.py              # Flask app: routes, DB, alert & insight logic
├── health_tracker.db    # created automatically on first run
├── templates/          # HTML pages (login, dashboard, entry form, history)
└── static/style.css    # styling
```
