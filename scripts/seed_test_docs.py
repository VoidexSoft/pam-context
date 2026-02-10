#!/usr/bin/env python3
"""
Seed Test Documents for PAM Context Development

Creates sample markdown documents in test_docs/ for development and evaluation
testing. These documents simulate realistic business knowledge artifacts.

Usage:
    python scripts/seed_test_docs.py
    python scripts/seed_test_docs.py --output-dir test_docs
"""

import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Document 1: Metrics Definitions
# ---------------------------------------------------------------------------

METRICS_DEFINITIONS = """\
# Product Metrics Definitions

**Owner:** Product Analytics Team
**Last Updated:** 2025-12-15
**Approved By:** VP of Product, Head of Data

---

## 1. User Engagement Metrics

### 1.1 DAU (Daily Active Users)

**Definition:** The count of unique users who performed at least one qualifying
action within a single calendar day (UTC).

**Qualifying Actions:**
- Page view (any authenticated page)
- Feature interaction (button click, form submission, search query)
- API call (authenticated endpoints only)

**Exclusions:**
- Bot traffic (identified via user-agent filtering and behavioral heuristics)
- Internal employee accounts (flagged via `is_internal = true` in users table)
- Accounts created in the last 24 hours (to avoid counting signup-only sessions)

**Data Source:** `analytics.user_activity_daily` in BigQuery
**Computation:** Airflow DAG `daily_user_rollup`, runs at 02:00 UTC
**Formula:** `COUNT(DISTINCT user_id) WHERE has_qualifying_action = true`

**Historical Note:** Prior to 2025-06-01, DAU included internal accounts. The
definition was updated per decision DOC-2025-0142 to align with investor
reporting standards.

---

### 1.2 WAU (Weekly Active Users)

**Definition:** The count of unique users who performed at least one qualifying
action within a rolling 7-day window ending on the measurement date.

**Data Source:** `analytics.user_activity_daily` (aggregated over 7 days)
**Formula:** `COUNT(DISTINCT user_id) WHERE activity_date BETWEEN date - 6 AND date`

---

### 1.3 MAU (Monthly Active Users)

**Definition:** The count of unique users who performed at least one qualifying
action within a rolling 28-day window ending on the measurement date.

**Why 28 days (not calendar month):** Using a fixed 28-day window ensures
consistent comparisons across months of different lengths.

**Data Source:** `analytics.user_activity_daily` (aggregated over 28 days)
**Formula:** `COUNT(DISTINCT user_id) WHERE activity_date BETWEEN date - 27 AND date`

---

### 1.4 Stickiness Ratio

**Definition:** DAU / MAU, expressed as a percentage. Measures how frequently
monthly users engage on a daily basis.

**Target:** > 25% (industry benchmark for B2B SaaS)
**Current:** 31% (as of 2025-12-01)

---

## 2. Revenue Metrics

### 2.1 MRR (Monthly Recurring Revenue)

**Definition:** The sum of all active subscription amounts normalized to a
monthly value.

**Calculation Rules:**
- Annual subscriptions: divide by 12
- Quarterly subscriptions: divide by 3
- Monthly subscriptions: use face value
- Trial accounts: excluded until conversion (`is_trial = false`)
- Paused accounts: excluded (`subscription_status != 'paused'`)

**Formula:**
```sql
SELECT SUM(
  CASE
    WHEN billing_interval = 'annual' THEN plan_price / 12
    WHEN billing_interval = 'quarterly' THEN plan_price / 3
    ELSE plan_price
  END
) AS mrr
FROM billing.subscriptions
WHERE subscription_status = 'active'
  AND is_trial = false
```

**Data Source:** `billing.subscriptions` in PostgreSQL (production database)
**Computation:** Airflow DAG `finance_metrics`, runs daily at 06:00 UTC
**Dashboard:** Finance Overview (Looker), Exec Weekly (Google Sheets)

---

### 2.2 ARR (Annual Recurring Revenue)

**Definition:** MRR * 12. Represents the annualized run-rate of recurring
revenue.

---

### 2.3 ARPU (Average Revenue Per User)

**Definition:** MRR divided by the count of paying accounts (excluding trials
and free tier).

**Formula:** `MRR / COUNT(accounts WHERE plan != 'free' AND is_trial = false)`

---

## 3. Conversion Metrics

### 3.1 Signup-to-Paid Conversion Rate

**Definition:** Percentage of users who signed up and converted to a paid plan
within 30 days of account creation.

**Formula:** `(paid_conversions_30d / total_signups) * 100`
**Attribution Window:** 30 days from signup date

---

### 3.2 Pricing Page Conversion Rate

**Definition:** The number of users who completed the `checkout_success` event
divided by the number of users who viewed the pricing page, expressed as a
percentage.

**Formula:** `(checkout_success_users / pricing_page_viewers) * 100`
**Attribution Window:** 30 days
**Data Source:** Segment events -> `events.raw_events` -> `analytics.funnel_daily`

**Note:** Prior to 2025-10-15, the checkout completion event was named
`purchase_complete`. It was renamed to `checkout_success` as part of the Q4
tracking plan update (see Tracking Plan v3, Section 2.1).

---

## 4. Retention Metrics

### 4.1 D1 / D7 / D30 Retention

**Definition:** The percentage of users who return and perform a qualifying
action on day 1, 7, or 30 after their first activity date.

**Formula:** `COUNT(users active on day N) / COUNT(users in cohort) * 100`

**Data Source:** `analytics.user_activity_daily` -> materialized view
`analytics.retention_cohorts_mv` (refreshed every 6 hours)

**Dashboard:** Retention Dashboard (Looker)
**Underlying table:** `analytics.user_activity_daily` in BigQuery, populated
by the `daily_user_rollup` Airflow DAG.

---

### 4.2 Net Revenue Retention (NRR)

**Definition:** Measures revenue retained from existing customers over a
12-month period, including expansion, contraction, and churn.

**Formula:**
```
NRR = (Starting MRR + Expansion - Contraction - Churn) / Starting MRR * 100
```

**Target:** > 110%
**Current:** 118% (as of 2025-Q4)

---

## 5. Data Freshness and Quality

| Metric | Source Table | Refresh Frequency | Staleness Alert |
|--------|-------------|-------------------|-----------------|
| DAU | analytics.user_activity_daily | Daily 02:00 UTC | > 4 hours |
| MRR | billing.subscriptions | Daily 06:00 UTC | > 6 hours |
| Conversion Rate | analytics.funnel_daily | Daily 03:00 UTC | > 4 hours |
| Retention | analytics.retention_cohorts_mv | Every 6 hours | > 8 hours |
| Event Volume | analytics.event_volume_daily | Daily 01:00 UTC | > 4 hours |
"""

# ---------------------------------------------------------------------------
# Document 2: Tracking Plan
# ---------------------------------------------------------------------------

TRACKING_PLAN = """\
# Product Tracking Plan v3

**Owner:** Sarah Chen, Senior Product Analyst
**Approver:** Product Analytics Team
**Implementation:** Growth Engineering Team
**Last Updated:** 2025-11-20
**Status:** Active

---

## 1. Overview

This document defines all product analytics events tracked across the
application. Any changes to event names, properties, or triggers must follow
the Event Change Request process (Section 6).

**Tracking Provider:** Segment (source: `app-web`, `app-ios`, `app-android`)
**Raw Event Store:** `events.raw_events` in BigQuery
**Event Volume Dashboard:** Analytics > Event Health (Looker)

---

## 2. Event Catalog

### 2.1 Signup Flow

| Event Name | Trigger | Properties |
|-----------|---------|------------|
| `signup_page_viewed` | User lands on /signup | `user_anonymous_id`, `utm_source`, `utm_medium`, `utm_campaign`, `device_type`, `browser`, `referrer_url` |
| `signup_form_started` | First form field interaction | `user_anonymous_id`, `utm_source`, `utm_medium`, `utm_campaign`, `device_type`, `browser` |
| `signup_email_entered` | Email field completed (blur) | `user_anonymous_id`, `email_domain`, `device_type`, `browser` |
| `signup_password_entered` | Password field completed (blur) | `user_anonymous_id`, `password_strength`, `device_type`, `browser` |
| `signup_submitted` | Form submit button clicked | `user_anonymous_id`, `signup_method` (email/google/github), `device_type`, `browser` |
| `signup_email_verified` | Email verification link clicked | `user_id`, `verification_delay_seconds`, `device_type` |
| `signup_completed` | Account fully created, user logged in | `user_id`, `signup_method`, `plan_selected`, `utm_source`, `utm_medium`, `utm_campaign`, `device_type` |

**Funnel Order:** signup_page_viewed -> signup_form_started -> signup_email_entered -> signup_password_entered -> signup_submitted -> signup_email_verified -> signup_completed

---

### 2.2 Core Product Usage

| Event Name | Trigger | Properties |
|-----------|---------|------------|
| `page_viewed` | Any authenticated page load | `user_id`, `page_path`, `page_title`, `referrer_path`, `session_id` |
| `feature_used` | Interaction with a named feature | `user_id`, `feature_name`, `feature_category`, `session_id` |
| `search_performed` | User submits a search query | `user_id`, `query_text`, `result_count`, `search_type`, `session_id` |
| `document_created` | New document created | `user_id`, `doc_type`, `template_used`, `project_id` |
| `document_shared` | Document shared with another user | `user_id`, `doc_id`, `share_type` (link/email/team), `recipient_count` |
| `export_completed` | User exports data or document | `user_id`, `export_format` (csv/pdf/xlsx), `row_count`, `doc_id` |

---

### 2.3 Billing and Conversion

| Event Name | Trigger | Properties |
|-----------|---------|------------|
| `pricing_page_viewed` | User views /pricing | `user_id`, `current_plan`, `referrer_path` |
| `plan_selected` | User clicks on a pricing tier | `user_id`, `selected_plan`, `billing_interval`, `current_plan` |
| `checkout_started` | Checkout form displayed | `user_id`, `selected_plan`, `billing_interval`, `coupon_code` |
| `checkout_success` | Payment processed successfully | `user_id`, `plan`, `billing_interval`, `amount_cents`, `currency`, `coupon_code`, `payment_method` |
| `checkout_failed` | Payment failed | `user_id`, `error_code`, `error_message`, `payment_method` |
| `subscription_cancelled` | User cancels subscription | `user_id`, `plan`, `cancel_reason`, `tenure_days` |
| `subscription_reactivated` | User reactivates after cancellation | `user_id`, `plan`, `days_since_cancel` |

**Note (v3 Change):** The event `purchase_complete` was renamed to
`checkout_success` on 2025-10-15. The old event name is deprecated and will
stop firing on 2026-01-15. Both events fire in parallel during the transition
period. All downstream queries must use `checkout_success`.

---

### 2.4 Notifications and Communication

| Event Name | Trigger | Properties |
|-----------|---------|------------|
| `notification_sent` | System sends notification | `user_id`, `notification_type`, `channel` (email/push/in-app) |
| `notification_opened` | User opens/clicks notification | `user_id`, `notification_type`, `channel`, `delay_seconds` |
| `email_unsubscribed` | User unsubscribes from email | `user_id`, `email_type`, `unsubscribe_reason` |

---

## 3. Global Properties

These properties are included on every event automatically by the Segment SDK:

| Property | Type | Description |
|----------|------|-------------|
| `timestamp` | ISO 8601 datetime | Event timestamp (client-side) |
| `received_at` | ISO 8601 datetime | Server receipt timestamp |
| `anonymous_id` | string | Pre-login anonymous identifier |
| `user_id` | string | Authenticated user ID (null if not logged in) |
| `context.device.type` | string | desktop / mobile / tablet |
| `context.browser.name` | string | Chrome / Safari / Firefox / etc. |
| `context.os.name` | string | macOS / Windows / iOS / Android |
| `context.locale` | string | User locale (e.g., en-US) |
| `context.page.url` | string | Full page URL |
| `context.campaign.source` | string | UTM source parameter |

---

## 4. Data Destinations

Events flow from Segment to:

| Destination | Purpose | Latency |
|-------------|---------|---------|
| BigQuery (`events.raw_events`) | Raw event store, analytics queries | < 5 min |
| Amplitude | Product analytics, funnel analysis | < 2 min |
| Braze | Marketing automation, user messaging | < 1 min |
| Looker (via BigQuery) | Dashboards and reporting | < 10 min |

---

## 5. Event Volume Monitoring

Expected daily event volumes (as of 2025-12-01):

| Event | Expected Volume | Alert Threshold |
|-------|----------------|-----------------|
| `page_viewed` | 500,000 - 700,000 | < 400,000 or > 900,000 |
| `feature_used` | 200,000 - 350,000 | < 150,000 or > 500,000 |
| `signup_page_viewed` | 5,000 - 8,000 | < 3,000 or > 12,000 |
| `checkout_success` | 200 - 400 | < 100 or > 600 |

Volume anomalies trigger PagerDuty alerts to the Product Analytics on-call.

---

## 6. Event Change Request Process

Any modification to tracked events must follow this process:

1. **Submit Request:** Create a Jira ticket (type: Event Change Request) with:
   - Current event name/properties
   - Proposed change
   - Reason for change
   - Impact assessment (list affected dashboards and queries)

2. **Review:** Tracking plan owner (Sarah Chen) reviews within 2 business days.

3. **Approval:** Requires sign-off from:
   - Tracking plan owner
   - At least one downstream consumer (dashboard owner or data analyst)

4. **Implementation:** Growth Engineering implements the change following the
   migration protocol.

5. **Migration Protocol:**
   - Phase 1: New event fires alongside old event (parallel tracking, minimum
     2 weeks)
   - Phase 2: All downstream queries migrated to new event name
   - Phase 3: Old event deprecated (stops firing after sunset date)
   - Sunset date must be at least 2 sprints (4 weeks) from deprecation notice

6. **Documentation:** Tracking plan updated, changelog entry added below.

---

## 7. Changelog

| Date | Change | Author |
|------|--------|--------|
| 2025-11-20 | v3: Updated global properties, added export_completed event | Sarah Chen |
| 2025-10-15 | v3: Renamed purchase_complete to checkout_success | Sarah Chen |
| 2025-08-01 | v2: Added notification events, subscription_reactivated | James Park |
| 2025-05-10 | v1: Initial tracking plan | Sarah Chen |
"""

# ---------------------------------------------------------------------------
# Document 3: Engineering Runbook
# ---------------------------------------------------------------------------

ENGINEERING_RUNBOOK = """\
# Platform Engineering Runbook

**Owner:** Platform Engineering Team
**On-Call Rotation:** PagerDuty schedule `platform-eng-oncall`
**Last Updated:** 2025-12-10
**Confluence:** Engineering > Runbooks (canonical version)

---

## 1. Service Overview

### 1.1 Production Services

| Service | Technology | Port | Health Check |
|---------|-----------|------|-------------|
| pam-api | FastAPI (Python 3.12) | 8000 | GET /api/status |
| pam-web | React 18 (Nginx) | 3000 | GET /health |
| pam-ingestion | Python workers | - | Heartbeat via Redis |
| elasticsearch | Elasticsearch 8.x | 9200 | GET _cluster/health |
| postgresql | PostgreSQL 16 | 5432 | pg_isready |
| redis | Redis 7.x | 6379 | PING |

### 1.2 Infrastructure

- **Cloud Provider:** AWS (us-east-1)
- **Orchestration:** ECS Fargate (production), Docker Compose (staging)
- **Monitoring:** Prometheus + Grafana
- **Alerting:** PagerDuty
- **Logging:** Structured JSON logs -> CloudWatch -> OpenSearch
- **CI/CD:** GitHub Actions

---

## 2. Ingestion Pipeline

### 2.1 SLA

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Pipeline uptime | 99.5% monthly | Any downtime > 5 min |
| Document processing latency | < 30 seconds (docs < 50 pages) | > 60 seconds |
| Webhook processing | < 5 minutes from receipt | > 10 minutes |
| Failed ingestion retry | 3 attempts, exponential backoff | All 3 failed |

### 2.2 Common Issues

#### Documents stuck in processing

**Symptoms:** Documents show `status = 'processing'` for > 10 minutes.

**Diagnosis:**
```bash
# Check processing queue depth
curl localhost:8000/api/status | jq '.ingestion.queue_depth'

# Check for stuck workers
docker logs pam-ingestion --tail 100 | grep ERROR

# Query stuck documents
psql -h localhost -U pam -d pam_context -c "
  SELECT id, source_url, status, started_at
  FROM documents
  WHERE status = 'processing'
    AND started_at < NOW() - INTERVAL '10 minutes'
  ORDER BY started_at;
"
```

**Resolution:**
1. If worker crashed: restart the ingestion service
2. If specific document fails repeatedly: mark as `status = 'error'` and
   investigate the document format
3. If queue is backed up: scale ingestion workers horizontally

---

## 3. Elasticsearch Operations

### 3.1 Cluster Health

**Healthy state:** Green (all primary and replica shards assigned)
**Warning state:** Yellow (all primaries assigned, some replicas missing)
**Critical state:** Red (some primary shards unassigned)

### 3.2 Red Cluster Recovery

**Symptoms:** `GET _cluster/health` returns `status: red`

**Step-by-step resolution:**

1. **Identify the problem:**
```bash
# Check cluster health
curl -s localhost:9200/_cluster/health | jq .

# Find unassigned shards and their reasons
curl -s 'localhost:9200/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason' | grep UNASSIGNED
```

2. **Disk space issue** (most common):
```bash
# Check disk usage
curl -s 'localhost:9200/_cat/allocation?v&h=node,disk.percent,disk.used,disk.avail'

# If disk > 85%, free space by deleting old indices
curl -X DELETE 'localhost:9200/pam-segments-2025-q1'

# Or expand storage (EBS volume resize)
```

3. **Node down:**
```bash
# Check which nodes are missing
curl -s 'localhost:9200/_cat/nodes?v'

# Check node logs
docker logs elasticsearch --tail 200

# Restart the node
docker restart elasticsearch
```

4. **Stuck shards:**
```bash
# Retry shard allocation
curl -X POST 'localhost:9200/_cluster/reroute?retry_failed=true'
```

5. **Escalation:** If not resolved within 15 minutes, escalate to the Platform
   Engineering on-call lead.

### 3.3 Index Management

```bash
# List all indices with sizes
curl -s 'localhost:9200/_cat/indices?v&h=index,docs.count,store.size&s=store.size:desc'

# Force refresh (make recent changes searchable)
curl -X POST 'localhost:9200/pam-segments/_refresh'

# Check index settings
curl -s 'localhost:9200/pam-segments/_settings' | jq .
```

---

## 4. PostgreSQL Operations

### 4.1 Connection Pool Exhaustion

**Symptoms:** API returns 500 errors, logs show "too many connections"

**Resolution:**
```bash
# Check current connections
psql -h localhost -U pam -d pam_context -c "
  SELECT count(*), state
  FROM pg_stat_activity
  GROUP BY state;
"

# Kill idle connections older than 10 minutes
psql -h localhost -U pam -d pam_context -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'idle'
    AND query_start < NOW() - INTERVAL '10 minutes';
"

# Long-term fix: increase pool size in config or investigate connection leaks
```

### 4.2 Slow Queries

```bash
# Find currently running slow queries
psql -h localhost -U pam -d pam_context -c "
  SELECT pid, now() - query_start AS duration, query
  FROM pg_stat_activity
  WHERE state = 'active'
    AND query_start < NOW() - INTERVAL '5 seconds'
  ORDER BY duration DESC;
"

# Check if autovacuum is running (can cause slowness)
psql -h localhost -U pam -d pam_context -c "
  SELECT relname, last_autovacuum, last_autoanalyze
  FROM pg_stat_user_tables
  WHERE schemaname = 'public'
  ORDER BY last_autovacuum DESC NULLS LAST;
"
```

---

## 5. API Service

### 5.1 Health Check

```bash
# Full health check (includes downstream services)
curl localhost:8000/api/status | jq .

# Expected response:
# {
#   "status": "healthy",
#   "services": {
#     "elasticsearch": "connected",
#     "postgresql": "connected",
#     "redis": "connected"
#   },
#   "ingestion": {
#     "queue_depth": 0,
#     "last_processed": "2025-12-10T14:30:00Z"
#   },
#   "version": "0.1.0"
# }
```

### 5.2 High Latency

**Normal latency:** p50 < 500ms, p95 < 2000ms, p99 < 5000ms

**If latency is elevated:**
1. Check Elasticsearch cluster health (slow queries cascade)
2. Check if reranker API is responding (Cohere endpoint)
3. Check LLM API latency (Anthropic status page)
4. Review recent deployments for regressions

### 5.3 Error Rate Spike

**Normal error rate:** < 1%

**If error rate > 5%:**
1. Check API logs: `docker logs pam-api --tail 500 | grep ERROR`
2. Check if it is a single endpoint or widespread
3. Check downstream service health
4. If caused by bad deployment: rollback via `./scripts/rollback.sh`

---

## 6. Incident Response

### 6.1 Severity Levels

| Level | Definition | Response Time | Example |
|-------|-----------|---------------|---------|
| SEV1 | System completely down | < 15 min | All API requests failing |
| SEV2 | Major feature broken | < 30 min | Search returning no results |
| SEV3 | Degraded performance | < 2 hours | Elevated latency (> 5s p95) |
| SEV4 | Minor issue | Next business day | Stale data in one dashboard |

### 6.2 Escalation Path

1. On-call engineer (PagerDuty)
2. Platform Engineering lead
3. VP of Engineering

### 6.3 Post-Incident

- Blameless post-mortem within 48 hours
- Action items tracked in Jira (label: `post-incident`)
- Runbook updated if a new failure mode was discovered
"""

# ---------------------------------------------------------------------------
# Document 4: Data Pipeline Architecture
# ---------------------------------------------------------------------------

DATA_PIPELINE_DOC = """\
# Data Pipeline Architecture

**Owner:** Data Engineering Team
**Last Updated:** 2025-11-28

---

## 1. Pipeline Overview

```
Raw Events (Segment)
    |
    v
BigQuery: events.raw_events (< 5 min latency)
    |
    +---> Airflow DAG: daily_user_rollup (02:00 UTC)
    |         |
    |         v
    |     BigQuery: analytics.user_activity_daily
    |         |
    |         +---> Materialized View: analytics.retention_cohorts_mv
    |         |     (refreshed every 6 hours)
    |         |
    |         +---> Airflow DAG: funnel_metrics (03:00 UTC)
    |                   |
    |                   v
    |               BigQuery: analytics.funnel_daily
    |
    +---> Airflow DAG: finance_metrics (06:00 UTC)
              |
              v
          BigQuery: analytics.revenue_daily
          (also reads from PostgreSQL: billing.subscriptions)
```

## 2. Key Tables

### events.raw_events
- **Source:** Segment BigQuery destination
- **Refresh:** Streaming (< 5 min)
- **Retention:** 13 months rolling
- **Partitioned by:** `received_at` (daily)
- **Clustered by:** `event`, `user_id`

### analytics.user_activity_daily
- **Source:** Aggregation of events.raw_events
- **Refresh:** Daily via `daily_user_rollup` DAG at 02:00 UTC
- **Schema:** user_id, activity_date, has_qualifying_action, session_count,
  page_view_count, feature_use_count, first_seen_date

### analytics.retention_cohorts_mv
- **Source:** Materialized view over analytics.user_activity_daily
- **Refresh:** Every 6 hours
- **Schema:** cohort_date, user_id, d1_retained, d7_retained, d30_retained

### analytics.funnel_daily
- **Source:** Aggregation of events.raw_events for funnel events
- **Refresh:** Daily via `funnel_metrics` DAG at 03:00 UTC
- **Schema:** date, funnel_name, step_name, unique_users, conversion_rate

### analytics.event_volume_daily
- **Source:** Count aggregation of events.raw_events by event type
- **Refresh:** Daily at 01:00 UTC
- **Schema:** date, event_name, event_count, unique_users
- **Purpose:** Event health monitoring, anomaly detection

## 3. Airflow DAGs

| DAG | Schedule | Owner | SLA |
|-----|----------|-------|-----|
| daily_user_rollup | 02:00 UTC | Data Eng | Complete by 03:00 UTC |
| funnel_metrics | 03:00 UTC | Data Eng | Complete by 04:00 UTC |
| finance_metrics | 06:00 UTC | Data Eng | Complete by 07:00 UTC |
| event_health_check | Every 1 hour | Data Eng | Alert within 5 min |
| retention_mv_refresh | Every 6 hours | Data Eng | Complete within 30 min |
"""

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

DOCUMENTS = {
    "metrics-definitions.md": METRICS_DEFINITIONS,
    "tracking-plan-v3.md": TRACKING_PLAN,
    "engineering-runbook.md": ENGINEERING_RUNBOOK,
    "data-pipeline-architecture.md": DATA_PIPELINE_DOC,
}


def main():
    parser = argparse.ArgumentParser(
        description="Seed test documents for PAM Context development",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent.parent / "test_docs"),
        help="Directory to write test documents (default: test_docs/)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Seeding test documents in {output_dir}/\n")

    for filename, content in DOCUMENTS.items():
        filepath = output_dir / filename
        filepath.write_text(content.strip() + "\n")
        line_count = len(content.strip().splitlines())
        print(f"  Created {filename} ({line_count} lines)")

    print(f"\nDone. {len(DOCUMENTS)} documents created in {output_dir}/")


if __name__ == "__main__":
    main()
