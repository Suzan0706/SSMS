# Connect SSMS to your PostgreSQL database (Windows, pgAdmin)

This connects the SSMS app (`ssms/api` + `ssms/web`) to a database you made in pgAdmin, for example
`smart_school_db` on PostgreSQL 18, so that everything entered in the app is saved there.

> **Kwa ufupi (Kiswahili):** Fungua `ssms\windows\setup.bat`, andika nenosiri la `postgres` likiulizwa, kisha
> fungua `ssms\windows\start.bat`. Programu itafunguka kwenye <http://localhost:5173> na kila kitu kitahifadhiwa
> kwenye `smart_school_db`. Usifute faili `ssms\api\.env`: lina funguo za kusimbua data.

## What you need

| Program | Version | Download |
|---|---|---|
| PostgreSQL (with pgAdmin) | 16 or newer (18 works) | <https://www.postgresql.org/download/windows/> |
| Python | 3.12 or newer, tick **Add python.exe to PATH** | <https://www.python.org/downloads/> |
| Node.js | 20 or newer (LTS) | <https://nodejs.org/> |

You need the password of the `postgres` user you chose when installing PostgreSQL.

## 1. Set up (once)

1. In pgAdmin, make sure the database exists (e.g. `smart_school_db`). It can be empty.
2. Double-click **`ssms\windows\setup.bat`**, or from a command prompt:

   ```bat
   ssms\windows\setup.bat smart_school_db
   ```

   For a trial with a sample school (only into an **empty** database):

   ```bat
   ssms\windows\setup.bat smart_school_db --demo
   ```

3. Type the `postgres` password when asked. It is used only during setup and is **not saved**.

The script ([`api/scripts/setup_database.py`](api/scripts/setup_database.py)):

- checks it can connect and that the database is either empty or already an SSMS database. If it holds tables from
  another program (for example the old `db/schema.sql`), it **stops without changing anything**;
- if SSMS data is already there, saves a backup with `pg_dump` to `ssms\backups\` before upgrading;
- creates the tables with the migrations (`alembic upgrade head`). Migrations only add; they never drop your data;
- writes `ssms\api\.env` with new secrets **once**. On later runs the secrets are kept and only the database lines
  change;
- creates the logins the app uses (`ssms_app`, `ssms_console`) and checks that `ssms_app` can sign in.

After setup, pgAdmin shows the SSMS tables under *smart_school_db → Schemas → public → Tables* (refresh with F5).

## 2. Start the app (every day)

Double-click **`ssms\windows\start.bat`**. It opens two windows (API and web) and then the browser at
<http://localhost:5173>. Keep both windows open while you use the app. API documentation: <http://127.0.0.1:8000/docs>.

With `--demo`: school code `mfano-sec`, user `admin`, password `Mfano@2026`.
Without demo data, create the platform (super-admin) account and then a school from the console at `/console`:

```bat
cd ssms\api
.venv\Scripts\python.exe scripts\setup_database.py --db smart_school_db --admin-email you@example.com
```

## 3. Keeping your data safe

- **Never delete or edit the secret lines in `ssms\api\.env`** (`SSMS_ENC_KEYS`, `SSMS_BLIND_INDEX_KEY`). Phone
  numbers and other sensitive fields are encrypted with them; without them they cannot be read. Keep a copy of
  `.env` somewhere safe (not in Git; it is already ignored).
- Back up regularly in pgAdmin (*right-click smart_school_db → Backup…*, format *Custom*) or:

  ```bat
  "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -U postgres -Fc -f smart_school_db.dump smart_school_db
  ```

- After pulling a new version of SSMS, run `setup.bat` again: it backs up, then applies only the new migrations.
- Do not create or change SSMS tables by hand in pgAdmin. Reading them is fine.

## Problems

| Message | Fix |
|---|---|
| `Cannot connect to database` | PostgreSQL service not running (Windows *Services* → `postgresql-x64-18`), wrong password, or the database name is different. |
| `... tables that were not made by SSMS` | The database already contains another schema. Make a new empty database in pgAdmin and run setup with its name. |
| `pg_dump was not found` | Add `C:\Program Files\PostgreSQL\18\bin` to PATH (setup.bat does this for version 18). |
| `password authentication failed for user "ssms_app"` | `.env` was copied from another computer. Run `setup.bat` again: it sets the password from your `.env`. |
| The web page opens but sign-in fails | The *SSMS API* window must be open and show `Application startup complete`. |

Settings you may change in `ssms\api\.env` are listed in [README.md § Environment variables](README.md#environment-variables).
This setup is for running on one computer (development mode, plain http). For a server, use Docker and
[design/18-operations.md](../design/18-operations.md).
