# 🚀 Ethan's Mission Control

Birthday party task tracker for Ethan's 2nd birthday — **Sunday, May 17, 2026**.

Two phases:
1. **Catch Air** (2:00–4:00 PM) — open play + party room
2. **Home** (~4:30–6:00 PM) — family dinner with Chinese food

This app coordinates every task across Pavel, Irina, Babushka, and Toby with a shared, browser-based command center.

---

## ✨ What it does

- **Day-grouped timeline** of every task with assignee, time, phase, and category
- **Sunday split into phases** (Phase 1 Setup → Catch Air → Transition → Phase 2 Setup → Home)
- **Check off / edit / add / delete** any task; changes persist instantly
- **Per-person progress chips** — tap one to filter to just that person's tasks
- **Search + filters** by day, status, assignee
- **Countdown** to liftoff (2:00 PM Sunday)
- **📧 Email export** — opens your mail app pre-filled with the formatted task list
- **📅 Calendar export** — downloads a `.ics` file you can drop into Google Calendar, iCloud, Outlook
  - Per-task calendar button on every card
  - Bulk export button for everything visible
- **Shared state across users** when deployed to a server (everyone sees the same checkboxes update in real time on refresh)
- **Falls back to localStorage** when run as a static file (no server needed)
- **Mobile-friendly** — Irina can update tasks from her phone while at Whole Foods

---

## 🏃 Quick start (local)

```bash
npm install
npm start
# → http://localhost:3000
```

---

## 🐳 Deploy to Unraid

### Option A — docker-compose (recommended)

1. SSH into your Unraid box (or use the terminal in the WebUI).
2. Copy the entire `ethan-bday` folder to `/mnt/user/appdata/ethan-bday`:
   ```bash
   mkdir -p /mnt/user/appdata/ethan-bday
   # then copy contents
   ```
3. Build and run:
   ```bash
   cd /mnt/user/appdata/ethan-bday
   docker compose up -d --build
   ```
4. Open `http://192.168.1.180:3010` (your Unraid IP + the host port from `docker-compose.yml`).

### Option B — Unraid Community Apps style

Add a new container in the Unraid UI with:

| Setting | Value |
|---|---|
| Name | `ethan-bday` |
| Repository | (build locally: `ethan-bday:latest`) |
| Network Type | Bridge |
| Port | Host `3010` → Container `3000` |
| Path | Host `/mnt/user/appdata/ethan-bday/data` → Container `/app/data` (Read/Write) |

---

## 🌐 Expose at ethan-tasks.pavelsherman.com

You already run a reverse proxy for `ethan.pavelsherman.com` and `nexus.pavelsherman.com`. Pattern matches — add an entry for the new subdomain pointing at `http://<unraid-ip>:3010`. If you use Nginx Proxy Manager, swordfish-fast: add a new Proxy Host, scheme `http`, forward hostname your Unraid IP, port `3010`, then attach your existing wildcard cert.

---

## 🗂️ File layout

```
ethan-bday/
├── Dockerfile
├── docker-compose.yml
├── package.json
├── server.js              # Express server + /api/tasks
├── data/
│   └── tasks.json         # Persisted state (volume-mounted)
└── public/
    └── index.html         # The whole frontend in one file
```

---

## 🔌 API

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/api/tasks` | — | `{ tasks: [...] }` |
| `PUT` | `/api/tasks` | `{ tasks: [...] }` | `{ ok: true, count: N }` |
| `GET` | `/api/health` | — | `{ ok: true, time: ... }` |

The frontend tries the API first; if it 404s (e.g. you opened the HTML file directly), it falls back to `localStorage`.

---

## 🔁 Reset / re-seed

To wipe state and re-seed from the original 31 tasks:
```bash
rm /mnt/user/appdata/ethan-bday/data/tasks.json
docker restart ethan-bday
```
The container repopulates from the bundled `data-seed/tasks.json` on startup.

---

## 📅 The plan (TL;DR)

- **Thu May 14** — Pavel: daycare $, Whole Foods recon, bowls, candle, card, text waivers. Irina: confirm daycare pizza, email Elina. Babushka: Costco.
- **Fri May 15** — Pavel: drop off Ethan. Irina: cupcakes @ noon → daycare; Mother's Day @ 4 PM. Babushka: ShopRite.
- **Sat May 16** — Clean house, pack Sunday gear, stage tables.
- **Sun May 17** —
  - AM: Toby gets cake, Babushka to house, Pavel picks up Emily & Ella at 11.
  - 1:15 PM: Irina + Toby leave with everything → Whole Foods → Catch Air.
  - 2:00 PM: Pavel arrives with Ethan. Open play.
  - 2:45 PM: Party room set-up with coordinator.
  - 3:20–4:00 PM: Eat, cake, gift bags.
  - 4:30–6:00 PM: Family at home, Chinese delivery, leftover cake.

🎂 Built with love (and a lot of moving parts).
