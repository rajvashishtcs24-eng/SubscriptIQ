# SubscriptIQ

**SubscriptIQ** is an advanced Subscription Management System built on Odoo 19.0 Community, developed for the Brightloop Software Hackathon.

---

## 👥 Team Module Ownership

All custom modules reside in the `custom_addons/` directory:

| Team Member | Module Name | Core Domain Responsibilities |
| :--- | :--- | :--- |
| **Member 1** | `subscriptiq_subscription` | Product management, variants, subscription plans, quotation management, subscription creation & lifecycle engine, event history, billing integration interfaces. |
| **Member 2** | `subscriptiq_billing` | Invoicing, payment processing, recurring billing engine, revenue recognition, financial reporting. |
| **Member 3** | `subscriptiq_portal` | Customer portal, self-service subscription management, usage tracking, client analytics. |

---

## 🛠️ Stack & Specifications

* **Odoo**: `19.0` (Community Edition, official `odoo:19.0` Docker image)
* **Database**: `PostgreSQL 16` (`postgres:16`)
* **Orchestration**: Docker Compose (Compose V2)
* **Custom Addons Mount**: `./custom_addons` mapped to `/mnt/extra-addons` inside container

---

## 📋 Prerequisites

Before running the application locally, ensure you have installed:

1. **Docker Desktop**:
   * Windows: Install [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/) with WSL 2 backend enabled.
   * Linux/macOS: Install Docker Engine with Docker Compose V2 support (`docker compose version` >= 2.20).
2. **Git**: Installed and configured.

---

## 🚀 Environment Setup

### 1. Configure Local Environment Variables

Duplicate the template configuration `.env.example` into `.env`:

**Windows PowerShell:**
```powershell
Copy-Item .env.example .env
```

**Bash / Linux / macOS:**
```bash
cp .env.example .env
```

Open `.env` and set a secure local password for PostgreSQL:
```env
POSTGRES_PASSWORD=your_secure_password_here
ODOO_PORT=8069
```

> [!NOTE]
> `.env` is explicitly ignored in `.gitignore` and should never be committed to Git.

---

## 🏃 Running the Stack

### Start Odoo and PostgreSQL Services

Start containers in detached (background) mode:

**Windows PowerShell / Bash:**
```powershell
docker compose up -d
```

Compose will:
1. Pull `postgres:16` and `odoo:19.0` if not present locally.
2. Initialize and start the PostgreSQL database container with health checks enabled.
3. Wait until PostgreSQL is completely healthy before booting the Odoo container.
4. Mount `./custom_addons` to `/mnt/extra-addons`.

### Verify Container Status

Check that both containers are running and healthy:

```powershell
docker compose ps
```

Expected output:
* `subscriptiq_db` — `Up (healthy)`
* `subscriptiq_odoo` — `Up`

---

## 🌐 Accessing the Application

* **Odoo Web Interface**: [http://localhost:8069](http://localhost:8069)
* **Odoo Longpolling (Livechat/Bus)**: `http://localhost:8072`

On initial launch, Odoo will display the database creation assistant. Use the master password and database credentials defined in your `.env`.

---

## 📂 Custom Addons Development

Custom modules are developed locally in the `custom_addons/` directory:

```
SubscriptIQ/
├── custom_addons/
│   ├── subscriptiq_subscription/  # Member 1
│   ├── subscriptiq_billing/       # Member 2
│   └── subscriptiq_portal/        # Member 3
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

Any files added inside `custom_addons/` are immediately mirrored into `/mnt/extra-addons` inside the Odoo container.

---

## 📜 Viewing Logs

To stream logs from all running services:
```powershell
docker compose logs -f
```

To view logs for a specific service:
```powershell
# Odoo application logs
docker compose logs -f web

# PostgreSQL database logs
docker compose logs -f db
```

---

## 🛑 Stopping the Environment

### Stop without deleting data (Preserves database & filestore):
```powershell
docker compose down
```

> [!IMPORTANT]
> The database and filestore are safely stored in named Docker volumes (`odoo-db-data` and `odoo-web-data`). Running `docker compose down` will safely shut down the containers while preserving all existing data.

### ⚠️ Warning: Do NOT remove volumes accidentally
Avoid using the `-v` / `--volumes` flag (`docker compose down -v`), as this permanently deletes PostgreSQL database volumes and uploaded files.
