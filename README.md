# SubscriptIQ - Enterprise Subscription & Governance Suite for Odoo 19

SubscriptIQ is an enterprise-grade subscription management architecture built natively on Odoo 19 and PostgreSQL 16. Engineered for regulatory compliance, security isolation, and seamless customer lifecycle management.

---

## 🏛 Core Architectural Pillars

| Component | Responsibility | Key Technologies |
| :--- | :--- | :--- |
| **Customer Self-Service Portal** | Client-facing subscription inspection, renewal tracking, plan details | Odoo Portal Engine, QWeb, XML, Controllers |
| **Staff & Identity Governance** | Segregated staff directory, complex authentication policies, role lockdown | res.users extension, Python Regex Constraints |
| **Tamper-Proof Audit Engine** | Immutable compliance logging of user lifecycle & configuration deltas | subscription.audit.log, Custom ORM Hooks |

---

## 🚀 Quickstart & Deployment

### Prerequisites
- Docker Engine 24.0+ & Docker Compose v2

### Launch Environment
\\\ash
# 1. Clone the repository
git clone https://github.com/rajvashishtcs24-eng/SubscriptIQ.git
cd SubscriptIQ

# 2. Configure environment (pre-configured defaults provided)
cp .env.example .env

# 3. Spin up PostgreSQL and Odoo services
docker compose up -d
\\\
Access the instance at \http://localhost:8069\.

---

## 🛡 Security & Compliance Architecture

### 1. Hardened Password Enforcement
Staff accounts strictly enforce strong password complexity via Python constraints (\models/res_users.py\):
- Minimum 9 characters
- At least 1 uppercase letter (\[A-Z]\)
- At least 1 lowercase letter (\[a-z]\)
- At least 1 numerical digit (\[0-9]\)
- At least 1 special symbol (\[!@#$%^&*...]\)

### 2. Role Elevation Lockdown
To prevent privilege escalation attacks:
- Non-administrators cannot grant, alter, or elevate membership within the Subscription Administrator or Staff security groups.
- Elevation violations immediately trigger an access rejection.

### 3. Immutable Business Audit Trail (\subscription.audit.log\)
Built specifically for financial, compliance, and governance requirements:
- **Audit Logging**: Intercepts user lifecycle actions (\USER_CREATED\, \USER_MODIFIED\) capturing actor ID, timestamp, target record, and an automated JSON payload delta.
- **Strict Immutability**: Any call to \write()\ or \unlink()\ raises a database-level \UserError\. Audit records cannot be altered or deleted by any user or administrator.
- **Portal Data Isolation**: Portal group access rules (\ir.rule\) enforce an empty query domain (\[('id', '=', False)]\), preventing data exposure over customer RPC channels.

---

## 🧭 Evaluator Walkthrough Guide

### Scenario A: Testing Customer Portal
1. Navigate to \http://localhost:8069/my\.
2. Notice the dedicated **Subscriptions** counter card under the portal home.
3. Access \http://localhost:8069/my/subscriptions\ to inspect subscription listings with status badges and recurring charges.
4. Select any subscription to view plan renewal intervals and customer invoice links.

### Scenario B: Validating Password Policy
1. Navigate to **Management & Config → Staff Management**.
2. Create or edit a staff member and assign a weak password (e.g., \password123\).
3. Observe the validation banner detailing the 5 security requirements.

### Scenario C: Verifying Audit Immutability
1. Under **Management & Config → Audit Trail**, view logged events with their actor metadata and change diffs.
2. Select an audit entry and click **Action → Delete**.
3. Confirm that the system blocks the deletion with an **Access Error: Audit records are immutable**.
