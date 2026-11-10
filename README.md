# EUnited

EUnited is a web platform for EUPeace students, built by the University of Mostar and the University of Calabria. This repository contains the first part, **the Pulse**: a news feed with mobility opportunities, events, scientific events, news and blog posts.

Euro-Chat and the Campus Mixer will be added as new Django apps next to `pulse/`.

## What works now

- **Feed** (`/`): newest posts first, mobile-first. You can filter by university, type and tag, and search posts.
- **Closing soon**: a strip at the top of the feed showing deadlines and events in the next 7 days.
- **Archive** (`/archive/`): posts whose deadline or event date has passed move here automatically.
- **Likes**: one per student per post.
- **Bell ("Remind me")**: follow a post to get an email and an in-app reminder 3 days and 1 day before the deadline. The bell icon in the header shows unread reminders.
- **Accounts**: sign up with a university email only (`@sum.ba`, `@unical.it`, including sub-domains). The account is confirmed with an email link. Log in with your email.
- **Student clubs** (`/submit/`): members of a verified club (for example SWITCH) submit posts. Every submission waits for approval.
- **Importer**: `python manage.py import_posts` reads the news of sum.ba, unical.it and eupeace.eu and adds every new item to the Review queue as a draft. See [The importer](#the-importer) below.
- **Admin panel** (`/admin/`):
  - The **Review queue** shows drafts and posts waiting for approval.
  - Actions: *Approve and publish*, *Reject* (the club sees the reason), *Hide*.
  - Roles:

    | Role | Access |
    |---|---|
    | Superadmin | Everything |
    | Editor | Writes and edits posts, but cannot publish. Editing a published post sends it back for approval |
    | Moderator | Can hide posts |
    | Student club | Submits posts |
    | Student | Reads, likes and sets reminders |

  - Change a user's role in *Users*.

## Not built yet (next steps)

- **Importer on a schedule, on the server**: `docker compose up` runs it every hour on your computer. The server needs its own cron job (see below).
- **Translate to English** button: needs a translation API key.
- **Discuss** button: becomes a link once Euro-Chat exists.
- Deploy. Hosting is decided later.

## Run it on your computer

**First time? Follow [SETUP.md](SETUP.md)**: a step-by-step guide for Mac, Windows and Linux, with the test accounts and fixes for common problems.

The quick way needs only Docker Desktop. One command starts the database, the site and the importer:

```bash
cd EUnited
docker compose up                # then open http://127.0.0.1:8000
```

It updates the tables, loads the sample data the first time, imports new posts every hour and sends the reminders every 10 minutes.

To run the site with your own Python instead (3.11 or newer), start only the database in Docker:

```bash
cd EUnited
docker compose up -d db          # PostgreSQL in Docker
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_demo       # sample data + test users
python manage.py runserver
```

Open http://127.0.0.1:8000. The admin panel is at http://127.0.0.1:8000/admin/.

Without Docker, install PostgreSQL yourself (on a Mac, for example [Postgres.app](https://postgresapp.com)), create the database with `createdb eunited` and run `export DATABASE_URL=postgres://localhost/eunited` in the terminal you use for the project.

`seed_demo` creates these test users. The password for all of them is `eunited-dev-123`.

| Email | Role |
|---|---|
| admin@sum.ba | Superadmin |
| editor@unical.it | Editor |
| moderator@sum.ba | Moderator |
| switch@sum.ba | SWITCH club account |
| student@unical.it | Student |

During development, emails (sign-up confirmation, reminders) are printed in the terminal instead of being sent.

### Useful commands

```bash
python manage.py test                  # run all tests
python manage.py seed_demo --reset     # delete all posts and reload sample data
python manage.py send_reminders        # send due reminders (run every ~10 min on the server)
python manage.py import_posts          # import new posts from the sources (run every hour on the server)
python manage.py import_posts --dry-run   # only show what would be imported
python manage.py createsuperuser       # create a real superadmin
```

## The importer

The importer reads the websites listed in *Sources* in the admin panel. A source is one of two kinds:

| Kind | Address to enter | How it works |
|---|---|---|
| RSS feed | The feed | Takes the title, summary, text and image of each item in the feed. |
| Scraping | The page that lists the news | Opens every news link on that page and reads its title, description and image (the Open Graph tags that sites add for social networks). The *link pattern* says which links are news. |

`seed_demo` adds these three sources:

| Source | Kind | Address |
|---|---|---|
| UNICAL news | RSS feed | `https://www.unical.it/contents/news/rss` |
| SUM news | Scraping | `https://www.sum.ba/objave/novosti` |
| EUPeace news | Scraping | `https://www.eupeace.eu/news/` |

What to know:

- Every imported post is a **draft of type News**, in the language of its source. Nothing reaches the Pulse until a superadmin publishes it. If it is really a mobility opportunity or an event, change the type and add the dates in the Review queue.
- A post is recognised by the address of its original page, so the same news is never imported twice. **Reject or hide** an imported post you don't want. If you delete it, the next run imports it again.
- One run takes at most 20 new posts from each source (`PULSE_IMPORT_LIMIT` in the settings).
- If a source can't be read, the command says why and goes on with the other sources.
- In the admin panel, select sources in *Sources* and choose *Import new posts from selected sources now* to run it by hand.
- On the server, run it every hour with cron: `0 * * * *  cd /path/to/EUnited && .venv/bin/python manage.py import_posts`

## Project structure

```
eunited/      settings and main URLs
accounts/     users (log in with email), roles, universities, student clubs, sign-up
pulse/        the Pulse: posts, tags, sources, likes, bell/follows, notifications
  models.py      data model (see the spec)
  services.py    likes, bell, reminder scheduling and sending
  importer.py    reads RSS feeds and news pages, creates drafts
  admin.py       admin panel + review queue
  views.py       feed, archive, post page, likes, bell, club submissions
  management/commands/   seed_demo, send_reminders, import_posts
templates/    base layout
static/css/   eunited.css (mobile-first styles, no framework)
static/fonts/ Archivo font files, self-hosted (OFL licence)
docker-compose.yml   the whole project for local development: database, site, background jobs
Dockerfile, docker/  the image of the site, and the scripts that start it
SETUP.md      step-by-step guide to run the project
```

## Rules the code enforces

- Only mobility opportunities and scientific events can have a **deadline**, and a mobility opportunity must have one.
- Only events and scientific events can have **event dates**, and an event must have a start date.
- `source_url` is unique, so the importer can't create the same post twice.
- Nothing appears in the feed unless its status is **Published**, and only superadmins can publish.
- Users who can't publish can only save a post as a draft or waiting for approval. If an editor changes a published post, it leaves the feed until a superadmin approves it again.

## Settings for production

| Variable | Meaning |
|---|---|
| `DJANGO_SECRET_KEY` | A long random string. Required. Once it is set, debug is off. |
| `DJANGO_DEBUG` | Leave it unset on the server. `1` turns debug on, for development only. |
| `DJANGO_ALLOWED_HOSTS` | For example `eunited.sum.ba` |
| `DATABASE_URL` | The PostgreSQL database, for example `postgres://user:password@host:5432/eunited` |
| `DJANGO_SITE_URL` | The site's public address, for example `https://eunited.sum.ba`. Used for the links in reminder emails. |
| `DJANGO_EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend`, plus the SMTP settings |

Without `DJANGO_SECRET_KEY` the project runs in development mode. Before going live, run `python manage.py check --deploy`.
