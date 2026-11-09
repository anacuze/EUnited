# Run EUnited on your computer

This guide gets the EUnited site running on your computer with sample posts and test accounts. The first time takes about 15 minutes; after that, starting it takes a few seconds.

How it works: **Docker runs only the database** (PostgreSQL). The site itself runs with Python directly on your computer, so when you change the code the server reloads by itself and you see the change straight away.

Commands are shown for **Mac and Linux**, with the **Windows** version where it differs. On Windows, use PowerShell.

---

## 1. Check what you need

| What | How to check | If it's missing |
|---|---|---|
| Docker Desktop, open and running | `docker --version`, and the whale icon is in the menu bar (Mac) or the system tray (Windows) | [docker.com](https://www.docker.com/products/docker-desktop/) |
| Git | `git --version` | Mac: `xcode-select --install` · Windows: [git-scm.com](https://git-scm.com/download/win) |
| Python 3.11 or newer | Mac/Linux: `python3 --version` · Windows: `py --version` | [python.org/downloads](https://www.python.org/downloads/) |
| Access to the repository | You can open https://github.com/anacuze/EUnited | Ask Ana to add you as a collaborator |

About Python:

- **Mac**: the Python that comes with macOS is often 3.9, which is too old. Install a recent one from python.org, or with Homebrew: `brew install python@3.13`.
- **Windows**: in the python.org installer, tick **"Add python.exe to PATH"** on the first screen.
- On a Mac, the command is `python3`, not `python`. Once the project environment is active (step 4), `python` works too.

## 2. Get the code

Open a terminal in the folder where you keep your projects, then:

```bash
git clone https://github.com/anacuze/EUnited.git
cd EUnited
```

Every command from here on is run **inside the `EUnited` folder**.

## 3. Start the database

Make sure Docker Desktop is open, then:

```bash
docker compose up -d
```

The first time, Docker downloads PostgreSQL, which takes a minute or two. Check that it is running:

```bash
docker compose ps
```

The `db` service should say `running` (or `Up`). The database is only reachable from your own computer, and its data is kept in a Docker volume, so it survives restarts.

## 4. Create the Python environment

The environment (`.venv`) keeps the project's packages separate from the rest of your computer. You create it once.

**Mac / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell says that running scripts is disabled, run this once and then try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

When the environment is active, the terminal prompt starts with `(.venv)`. Now install the packages:

```bash
pip install -r requirements.txt
```

## 5. Create the tables and the sample data

```bash
python manage.py migrate
python manage.py seed_demo
```

`migrate` creates the tables in the database. `seed_demo` adds sample posts (marked "(sample)"), the universities, the SWITCH club and the test accounts below.

## 6. Start the site

```bash
python manage.py runserver
```

Open **http://127.0.0.1:8000** in your browser. The admin panel is at **http://127.0.0.1:8000/admin/**.

Leave this terminal open while you work: the server runs there and shows every request. To stop it, press `Ctrl+C`.

## 7. Log in with the test accounts

The password is **`eunited-dev-123`** for every account.

| Email | Role | Good for trying |
|---|---|---|
| `student@unical.it` | Student | Likes, "Remind me", the reminders page |
| `switch@sum.ba` | SWITCH club | *Submit a post* in the menu |
| `editor@unical.it` | Editor | Writing posts in the admin panel (can't publish) |
| `moderator@sum.ba` | Moderator | Hiding posts in the admin panel |
| `admin@sum.ba` | Superadmin | Everything, including the *Review queue* |

No real email is sent during development. The sign-up confirmation and the reminders are printed in the terminal where `runserver` is running: copy the link from there to confirm a new account.

These accounts are for development only. Never run `seed_demo` on the live site.

---

## Every time after the first

```bash
cd EUnited
docker compose up -d                 # only if Docker was closed or the computer restarted
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
git pull                             # get the latest changes
pip install -r requirements.txt      # only needed if requirements.txt changed
python manage.py migrate             # safe to run every time
python manage.py runserver
```

## Run the tests

```bash
python manage.py test
```

It should end with `OK`. The tests use their own database, which Django creates and deletes by itself, so your sample data is not touched. Run them before every push.

## Useful commands

| Command | What it does |
|---|---|
| `python manage.py seed_demo --reset` | Deletes all posts and loads the sample posts again |
| `python manage.py send_reminders` | Sends the reminders that are due (printed in the terminal) |
| `python manage.py createsuperuser` | Creates a superadmin with your own email |
| `docker compose stop` | Stops the database and keeps the data |
| `docker compose down -v` | Deletes the database **and all its data**, to start from zero |

---

## If something goes wrong

**`command not found: python`** (Mac)
The environment isn't active. Run `source .venv/bin/activate`, or use `python3` outside the environment.

**`connection refused` … `port 5432`** or **`could not connect to server`**
The database isn't running. Open Docker Desktop, run `docker compose up -d`, and check with `docker compose ps`.

**`port is already allocated`** when starting the database
Another PostgreSQL is already using port 5432, for example Postgres.app or one installed with Homebrew. Stop it (Postgres.app: *Stop*; Homebrew: `brew services stop postgresql`; Windows: stop the "postgresql" service in *Services*) and run `docker compose up -d` again.

**`Error: That port is already in use`** when starting the site
Another `runserver` is already open in some terminal. Close it, or start this one on another port: `python manage.py runserver 8001`.

**"Wrong email or password"** with the test accounts
The sample data isn't there yet. Run `python manage.py seed_demo`.

**The page looks unstyled or doesn't show the latest changes**
The browser is showing an old copy of the styles. Reload with `Cmd+Shift+R` (Mac) or `Ctrl+F5` (Windows).

**`pip install` fails**
Check `python --version` (it must be 3.11 or newer), update pip with `python -m pip install --upgrade pip`, then try again.

**Start again from scratch**
`docker compose down -v`, then steps 3 and 5 again. This deletes everything in your local database.
