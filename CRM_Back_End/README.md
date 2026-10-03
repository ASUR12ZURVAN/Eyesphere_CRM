# Eyesphere CareBuddy CRM

A single-user Django CRM for lead intake, patient profiles, call tracking, follow-ups, bookings and sales reporting. The interface is designed for the Eyesphere light-blue and white workspace.

## Run locally

From the repository root in PowerShell:

```powershell
.\CRMenv\Scripts\Activate.ps1
cd .\CRM_Back_End
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/` and sign in with the account created above. The admin console is available at `/admin/`.

## Workflows

- Search and filter leads, add or edit a patient profile, and export the current filtered inventory.
- Record call outcomes. No-contact outcomes schedule the next weekday retry; the fourth closes the lead as Waste. A conversation resets the retry sequence while retaining every call.
- Schedule and snooze follow-ups, reactivate rejected or waste leads with a reason, and create bookings with insurance and execution values.
- Import CSV files after preview and validation. Required headers are `Name`, `Mobile`, and `Source`; `Campaign`, `Location`, `Email`, and `External Source ID` are also recognized. Existing mobiles and source IDs are skipped.
- Export daily calling, call history, bookings, revenue, source conversion, and lost-reason reports from the dashboard.

Run the focused regression suite with:

```powershell
python manage.py test lead
```

Google Sheets, Gmail, WhatsApp messaging, and telephony are external integrations and are not enabled in this MVP. Before deployment, configure a production `SECRET_KEY`, `DEBUG=False`, allowed hosts, HTTPS, and a database backup policy.

The database connection is read from `DATABASE_URL`. Set it to the connection URL provided by Neon; SSL is required. Install the backend dependencies from the repository root with `pip install -r .\CRM_Back_End\requirements.txt`.