#!/usr/bin/env python3
"""
backend/audit/audit_day1_afternoon.py
Day 1 Afternoon Block Audit — DB Lifespan · Storage · Schema · Migration
Run: python -m backend.audit.audit_day1_afternoon

Checks 4 task groups, 32 total checks.
Scoring: PASS=1, WARN=0.5, FAIL=0
Target: 28/32 (87%) to unlock Day 2 tasks.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from dataclasses import dataclass, field

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
PASS   = f"{GREEN}✅ PASS{RESET}"
FAIL   = f"{RED}❌ FAIL{RESET}"
WARN   = f"{YELLOW}⚠️  WARN{RESET}"

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND_ROOT = Path(__file__).resolve().parents[2]   # …/backend/
REPO_ROOT    = BACKEND_ROOT.parent                   # project root

PATHS = {
    "main"       : BACKEND_ROOT / "main.py",
    "db"         : BACKEND_ROOT / "shared" / "db.py",
    "models"     : BACKEND_ROOT / "shared" / "models.py",
    "lead_model" : BACKEND_ROOT / "models"  / "lead.py",
    "repo"       : BACKEND_ROOT / "shared"  / "repository.py",
    "alembic_ini": BACKEND_ROOT / "alembic.ini",
    "alembic_env": BACKEND_ROOT / "alembic"  / "env.py",
    "alembic_ver": BACKEND_ROOT / "alembic"  / "versions",
}

@dataclass
class Check:
    id       : str
    name     : str
    task     : str
    result   : str = "FAIL"     # PASS | WARN | FAIL
    detail   : str = ""
    fix      : str = ""
    score    : float = 0.0

@dataclass
class AuditReport:
    checks   : list[Check] = field(default_factory=list)

    def add(self, c: Check) -> None:
        self.checks.append(c)

    def score(self) -> tuple[float, float]:
        earned = sum(c.score for c in self.checks)
        total  = len(self.checks)
        return earned, total

    def by_task(self) -> dict[str, list[Check]]:
        tasks: dict[str, list[Check]] = {}
        for c in self.checks:
            tasks.setdefault(c.task, []).append(c)
        return tasks


# ── Helpers ───────────────────────────────────────────────────────────────────

def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""

def contains(text: str, *patterns: str) -> bool:
    return all(re.search(p, text) for p in patterns)

def not_contains(text: str, *patterns: str) -> bool:
    return all(not re.search(p, text) for p in patterns)

def grep_rn(pattern: str, *dirs: Path) -> list[tuple[Path, int, str]]:
    """Return (file, line_no, line_text) for all matches."""
    hits = []
    for d in dirs:
        for f in d.rglob("*.py"):
            for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                if re.search(pattern, line):
                    hits.append((f, i, line.strip()))
    return hits

def count_columns_in_model(text: str, col_names: list[str]) -> list[str]:
    """Return which column names are present as Column() assignments."""
    found = []
    for name in col_names:
        if re.search(rf"\b{name}\s*[:=].*Column\(", text):
            found.append(name)
    return found

def alembic_versions_exist() -> list[Path]:
    d = PATHS["alembic_ver"]
    if not d.exists():
        return []
    return [f for f in d.iterdir() if f.suffix == ".py" and f.name != "__init__.py"]


# ══════════════════════════════════════════════════════════════════════════════
#  TASK 2.1 — DB Engine Lifespan (8 checks)
# ══════════════════════════════════════════════════════════════════════════════

def audit_task_21(report: AuditReport) -> None:
    TASK = "Task 2.1 — DB Lifespan"
    main_src = read(PATHS["main"])
    db_src   = read(PATHS["db"])

    # ── Check 2.1.1: engine imported in main.py ────────────────────────────
    c = Check("2.1.1", "engine_imported_in_main", TASK)
    if re.search(r"from backend\.shared\.db import.*engine", main_src) or \
       re.search(r"from \.shared.db import.*engine", main_src):
        c.result, c.score, c.detail = "PASS", 1.0, "engine imported from shared.db"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "engine not imported in main.py"
        c.fix    = "Add: from backend.shared.db import engine"
    report.add(c)

    # ── Check 2.1.2: SELECT 1 probe in lifespan ────────────────────────────
    c = Check("2.1.2", "select1_probe_in_lifespan", TASK)
    if re.search(r"SELECT 1", main_src, re.IGNORECASE) or \
       re.search(r"text\(['\"]+SELECT 1", main_src, re.IGNORECASE):
        c.result, c.score, c.detail = "PASS", 1.0, "SELECT 1 probe found in lifespan"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "No SELECT 1 probe — DB not verified at startup"
        c.fix    = "Add: await conn.execute(text('SELECT 1')) inside lifespan startup"
    report.add(c)

    # ── Check 2.1.3: text() imported for raw SQL ───────────────────────────
    c = Check("2.1.3", "sqlalchemy_text_imported", TASK)
    if re.search(r"from sqlalchemy import.*text", main_src) or \
       re.search(r"from sqlalchemy.sql import.*text", main_src):
        c.result, c.score, c.detail = "PASS", 1.0, "sqlalchemy text() imported"
    else:
        c.result, c.score = "WARN", 0.5
        c.detail = "text() not imported — SELECT 1 may fail at runtime"
        c.fix    = "Add: from sqlalchemy import text"
    report.add(c)

    # ── Check 2.1.4: engine.dispose() in shutdown ──────────────────────────
    c = Check("2.1.4", "engine_dispose_on_shutdown", TASK)
    if re.search(r"engine\.dispose\(\)", main_src):
        c.result, c.score, c.detail = "PASS", 1.0, "engine.dispose() present in shutdown"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "engine.dispose() missing — connections leak on shutdown"
        c.fix    = "Add: await engine.dispose() in lifespan shutdown block"
    report.add(c)

    # ── Check 2.1.5: DB failure = hard raise (not warning) ────────────────
    c = Check("2.1.5", "db_failure_raises_not_warns", TASK)
    lifespan_block = re.search(
        r"async def lifespan.*?yield", main_src, re.DOTALL
    )
    if lifespan_block:
        block = lifespan_block.group(0)
        # Check if DB section has "raise" not just "logger.warning"
        if re.search(r"db.*?raise|raise.*?db", block, re.IGNORECASE | re.DOTALL):
            c.result, c.score, c.detail = "PASS", 1.0, "DB failure raises — hard fail on startup"
        elif re.search(r"SELECT 1", block, re.IGNORECASE):
            c.result, c.score = "WARN", 0.5
            c.detail = "SELECT 1 present but no explicit raise on DB failure"
            c.fix    = "Wrap DB probe in try/except that raises (not warns) on failure"
        else:
            c.result, c.score = "FAIL", 0.0
            c.detail = "No DB probe in lifespan"
            c.fix    = "Add DB probe with raise on failure"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "lifespan function not found"
    report.add(c)

    # ── Check 2.1.6: NullPool configured ──────────────────────────────────
    c = Check("2.1.6", "nullpool_configured", TASK)
    if re.search(r"NullPool", db_src):
        c.result, c.score, c.detail = "PASS", 1.0, "NullPool configured (Supavisor compatible)"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "NullPool not set — breaks Supabase connection pooler"
        c.fix    = "Add: poolclass=NullPool to create_async_engine()"
    report.add(c)

    # ── Check 2.1.7: port 6543 enforced ───────────────────────────────────
    c = Check("2.1.7", "supavisor_port_6543", TASK)
    if re.search(r":6543/", db_src) or re.search(r"6543", db_src):
        c.result, c.score, c.detail = "PASS", 1.0, "Port 6543 enforced for Supavisor"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "Port 6543 not enforced — Supabase transactions will fail"
        c.fix    = "Replace :5432/ with :6543/ in database URL"
    report.add(c)

    # ── Check 2.1.8: statement_cache_size=0 ───────────────────────────────
    c = Check("2.1.8", "statement_cache_disabled", TASK)
    if re.search(r"statement_cache_size.*0", db_src):
        c.result, c.score, c.detail = "PASS", 1.0, "statement_cache_size=0 set"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "statement_cache_size not disabled — asyncpg + NullPool will error"
        c.fix    = "Add statement_cache_size=0 to connect_args"
    report.add(c)


# ══════════════════════════════════════════════════════════════════════════════
#  TASK 2.2 — Mock Storage Replacement (8 checks)
# ══════════════════════════════════════════════════════════════════════════════

def audit_task_22(report: AuditReport) -> None:
    TASK = "Task 2.2 — Mock Storage Removal"
    repo_src = read(PATHS["repo"])
    backend  = BACKEND_ROOT

    # ── Check 2.2.1: No fake_leads references ─────────────────────────────
    c = Check("2.2.1", "no_fake_leads_pattern", TASK)
    hits = grep_rn(r"fake_leads|mock_leads|sample_leads", backend)
    if not hits:
        c.result, c.score, c.detail = "PASS", 1.0, "No fake_leads patterns found"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = f"Found {len(hits)} fake_leads references: " + \
                   ", ".join(f"{h[0].name}:{h[1]}" for h in hits[:3])
        c.fix    = "Replace all fake_leads with real DB writes via LeadRepo.upsert()"
    report.add(c)

    # ── Check 2.2.2: No /src/data/ fake JSON paths ────────────────────────
    c = Check("2.2.2", "no_src_data_paths", TASK)
    hits = grep_rn(r"/src/data/|src[/\\\\]data[/\\\\]", backend)
    src_data_dir = REPO_ROOT / "src" / "data"
    dir_exists = src_data_dir.exists()
    if not hits and not dir_exists:
        c.result, c.score, c.detail = "PASS", 1.0, "/src/data/ directory and references removed"
    elif dir_exists:
        c.result, c.score = "FAIL", 0.0
        c.detail = "/src/data/ directory still exists"
        c.fix    = "Delete /src/data/ and remove all imports referencing it"
    else:
        c.result, c.score = "WARN", 0.5
        c.detail = f"/src/data/ references in code: {len(hits)}"
        c.fix    = "Clean all import references to /src/data/"
    report.add(c)

    # ── Check 2.2.3: LeadRepo.upsert uses pg_insert ON CONFLICT ───────────
    c = Check("2.2.3", "upsert_uses_on_conflict", TASK)
    if re.search(r"on_conflict_do_update", repo_src) and \
       re.search(r"pg_insert|insert.*Lead", repo_src):
        c.result, c.score, c.detail = "PASS", 1.0, "pg_insert ON CONFLICT DO UPDATE present"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "LeadRepo.upsert() lacks idempotent ON CONFLICT — duplicate leads possible"
        c.fix    = "Use pg_insert().on_conflict_do_update() for idempotency"
    report.add(c)

    # ── Check 2.2.4: session.flush() after insert ─────────────────────────
    c = Check("2.2.4", "session_flush_after_insert", TASK)
    if re.search(r"await self\._s\.flush\(\)", repo_src) or \
       re.search(r"await session\.flush\(\)", repo_src):
        c.result, c.score, c.detail = "PASS", 1.0, "session.flush() present to get ID pre-commit"
    else:
        c.result, c.score = "WARN", 0.5
        c.detail = "session.flush() not called — lead.id may be None before Redis publish"
        c.fix    = "Add: await self._s.flush() after session.add(lead)"
    report.add(c)

    # ── Check 2.2.5: DB write BEFORE Redis publish ─────────────────────────
    c = Check("2.2.5", "db_write_before_redis_publish", TASK)
    workers_dir = BACKEND_ROOT / "workers" if (BACKEND_ROOT / "workers").exists() \
                  else BACKEND_ROOT / "ingestion"
    worker_hits_redis_before_db = []
    if workers_dir.exists():
        for wf in workers_dir.rglob("*.py"):
            wt = wf.read_text(errors="ignore")
            # Find if redis publish appears before upsert in same function
            publish_pos = [m.start() for m in re.finditer(r"redis.*publish|xadd|XADD", wt, re.IGNORECASE)]
            upsert_pos  = [m.start() for m in re.finditer(r"\.upsert|session\.add|await.*repo", wt)]
            if publish_pos and upsert_pos:
                if min(publish_pos) < min(upsert_pos):
                    worker_hits_redis_before_db.append(wf.name)
    if not worker_hits_redis_before_db:
        c.result, c.score, c.detail = "PASS", 1.0, "No Redis-before-DB ordering violation found"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = f"Redis publish before DB write in: {worker_hits_redis_before_db}"
        c.fix    = "Kleppmann rule: DB write → flush → Redis publish (never reverse)"
    report.add(c)

    # ── Check 2.2.6: QuotaRepo.increment wired for token tracking ─────────
    c = Check("2.2.6", "quota_repo_increment_present", TASK)
    if re.search(r"class QuotaRepo", repo_src) and \
       re.search(r"async def increment", repo_src):
        c.result, c.score, c.detail = "PASS", 1.0, "QuotaRepo.increment() present for token tracking"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "QuotaRepo.increment() missing — DB token accounting broken"
        c.fix    = "Add QuotaRepo with increment(model, tokens) using ON CONFLICT DO UPDATE"
    report.add(c)

    # ── Check 2.2.7: No bare list() mock returns in workers ───────────────
    c = Check("2.2.7", "no_hardcoded_lead_lists", TASK)
    hits = grep_rn(r"return\s+\[\s*\]|return\s+\[\s*Lead\(|fake_lead\s*=", backend)
    hits = [h for h in hits if "test" not in str(h[0]).lower() and "audit" not in str(h[0]).lower()]
    if not hits:
        c.result, c.score, c.detail = "PASS", 1.0, "No hardcoded empty/mock lead lists in production code"
    else:
        c.result, c.score = "WARN", 0.5
        c.detail = f"{len(hits)} hardcoded lead returns: " + \
                   ", ".join(f"{h[0].name}:{h[1]}" for h in hits[:3])
        c.fix    = "Replace with real LeadRepo.list_all() calls"
    report.add(c)

    # ── Check 2.2.8: get_db_session used as context manager ───────────────
    c = Check("2.2.8", "get_db_session_as_context_manager", TASK)
    db_src = read(PATHS["db"])
    if re.search(r"@asynccontextmanager", db_src) and \
       re.search(r"async def get_db_session", db_src):
        c.result, c.score, c.detail = "PASS", 1.0, "get_db_session is proper async context manager"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "get_db_session not an asynccontextmanager — sessions won't auto-close"
        c.fix    = "Decorate with @asynccontextmanager and use yield"
    report.add(c)


# ══════════════════════════════════════════════════════════════════════════════
#  TASK 2.3 — Schema / Model Columns (8 checks)
# ══════════════════════════════════════════════════════════════════════════════

def audit_task_23(report: AuditReport) -> None:
    TASK = "Task 2.3 — DB Schema Columns"
    # shared/models.py is the CANONICAL model — use it
    models_src = read(PATHS["models"])

    REQUIRED_COLS = {
        "is_opportunity" : r"is_opportunity.*Column.*Boolean",
        "confidence"     : r"confidence.*Column.*Float",
        "intent"         : r"intent.*Column.*String",
        "urgency"        : r"urgency.*Column.*String",
        "analyzed_at"    : r"analyzed_at.*Column.*DateTime",
        "scored_at"      : r"scored_at.*Column.*DateTime",
        "post_id"        : r"post_id.*Column.*UUID.*ForeignKey",
        "outreach_draft" : r"outreach_draft.*Column.*Text",
    }

    # ── Check 2.3.1-2.3.8: One per required column ────────────────────────
    col_checks = [
        ("2.3.1", "col_is_opportunity",  "is_opportunity",  REQUIRED_COLS["is_opportunity"]),
        ("2.3.2", "col_confidence",       "confidence",      REQUIRED_COLS["confidence"]),
        ("2.3.3", "col_intent",           "intent",          REQUIRED_COLS["intent"]),
        ("2.3.4", "col_urgency",          "urgency",         REQUIRED_COLS["urgency"]),
        ("2.3.5", "col_analyzed_at",      "analyzed_at",     REQUIRED_COLS["analyzed_at"]),
        ("2.3.6", "col_scored_at",        "scored_at",       REQUIRED_COLS["scored_at"]),
        ("2.3.7", "col_post_id_fk",       "post_id FK",      REQUIRED_COLS["post_id"]),
        ("2.3.8", "col_outreach_draft",   "outreach_draft",  REQUIRED_COLS["outreach_draft"]),
    ]

    for check_id, name, col_name, pattern in col_checks:
        c = Check(check_id, name, TASK)
        if re.search(pattern, models_src, re.IGNORECASE):
            c.result, c.score, c.detail = "PASS", 1.0, f"Column {col_name} present in Lead model"
        else:
            c.result, c.score = "FAIL", 0.0
            c.detail = f"Column {col_name} MISSING from shared/models.py Lead class"
            c.fix    = f"Add {col_name} = Column(...) to Lead in shared/models.py"
        report.add(c)


# ══════════════════════════════════════════════════════════════════════════════
#  TASK 2.4 — Alembic Migration (8 checks)
# ══════════════════════════════════════════════════════════════════════════════

def audit_task_24(report: AuditReport) -> None:
    TASK = "Task 2.4 — Alembic Migration"
    alembic_ini = read(PATHS["alembic_ini"])
    alembic_env = read(PATHS["alembic_env"])
    versions    = alembic_versions_exist()

    # ── Check 2.4.1: alembic.ini exists ────────────────────────────────────
    c = Check("2.4.1", "alembic_ini_exists", TASK)
    if PATHS["alembic_ini"].exists() and alembic_ini:
        c.result, c.score, c.detail = "PASS", 1.0, "alembic.ini found"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "alembic.ini missing — run: alembic init alembic"
        c.fix    = "cd backend && alembic init alembic"
    report.add(c)

    # ── Check 2.4.2: async env.py setup ────────────────────────────────────
    c = Check("2.4.2", "alembic_async_env", TASK)
    if re.search(r"AsyncEngine|run_async_migrations|asyncio", alembic_env):
        c.result, c.score, c.detail = "PASS", 1.0, "Async Alembic env.py configured"
    elif alembic_env:
        c.result, c.score = "FAIL", 0.0
        c.detail = "env.py is synchronous — will fail with async SQLAlchemy engine"
        c.fix    = "Add asyncio.run(run_async_migrations()) pattern to env.py"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "alembic/env.py not found"
        c.fix    = "Run: alembic init alembic && configure env.py for async"
    report.add(c)

    # ── Check 2.4.3: target_metadata set ──────────────────────────────────
    c = Check("2.4.3", "alembic_target_metadata", TASK)
    if re.search(r"target_metadata\s*=\s*Base\.metadata|target_metadata\s*=.*\.metadata", alembic_env):
        c.result, c.score, c.detail = "PASS", 1.0, "target_metadata = Base.metadata set"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "target_metadata not set — autogenerate won't detect model changes"
        c.fix    = "Set: target_metadata = Base.metadata in env.py"
    report.add(c)

    # ── Check 2.4.4: At least one migration version file exists ───────────
    c = Check("2.4.4", "migration_version_exists", TASK)
    if versions:
        c.result, c.score, c.detail = "PASS", 1.0, f"{len(versions)} migration file(s) found"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "No migration files in alembic/versions/ — schema was never versioned"
        c.fix    = "Run: alembic revision --autogenerate -m 'initial_schema'"
    report.add(c)

    # ── Check 2.4.5: upgrade() function in latest migration ───────────────
    c = Check("2.4.5", "migration_has_upgrade", TASK)
    if versions:
        latest = sorted(versions)[-1]
        content = latest.read_text(errors="ignore")
        if re.search(r"def upgrade\(\)", content) and \
           re.search(r"op\.", content):
            c.result, c.score, c.detail = "PASS", 1.0, f"upgrade() with op.* calls found in {latest.name}"
        else:
            c.result, c.score = "WARN", 0.5
            c.detail = f"upgrade() in {latest.name} has no op.* calls — migration may be empty"
            c.fix    = "Ensure upgrade() contains op.create_table() or op.add_column() calls"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "No version files to check"
    report.add(c)

    # ── Check 2.4.6: downgrade() function in latest migration ─────────────
    c = Check("2.4.6", "migration_has_downgrade", TASK)
    if versions:
        latest = sorted(versions)[-1]
        content = latest.read_text(errors="ignore")
        if re.search(r"def downgrade\(\)", content) and \
           re.search(r"op\.", content):
            c.result, c.score, c.detail = "PASS", 1.0, f"downgrade() with op.* calls found in {latest.name}"
        else:
            c.result, c.score = "WARN", 0.5
            c.detail = "downgrade() exists but has no op.* calls — migration not reversible"
            c.fix    = "Kleppmann: every upgrade must have exact inverse in downgrade()"
    else:
        c.result, c.score = "FAIL", 0.0
        c.detail = "No version files to check"
    report.add(c)

    # ── Check 2.4.7: No datetime.utcnow() usage (deprecated) ─────────────
    c = Check("2.4.7", "no_utcnow_deprecated", TASK)
    models_src = read(PATHS["models"])
    hits = re.findall(r"datetime\.utcnow\(\)", models_src)
    if not hits:
        c.result, c.score, c.detail = "PASS", 1.0, "No deprecated datetime.utcnow() found"
    else:
        c.result, c.score = "WARN", 0.5
        c.detail = f"{len(hits)} datetime.utcnow() calls — deprecated in Python 3.12"
        c.fix    = "Replace with: datetime.now(UTC) — already imported as UTC in models.py"
    report.add(c)

    # ── Check 2.4.8: UniqueConstraint on post_id ──────────────────────────
    c = Check("2.4.8", "unique_constraint_post_id", TASK)
    models_src = read(PATHS["models"])
    if re.search(r"UniqueConstraint.*post_id|post_id.*UniqueConstraint", models_src):
        c.result, c.score, c.detail = "PASS", 1.0, "UniqueConstraint on post_id prevents duplicate leads"
    else:
        c.result, c.score = "WARN", 0.5
        c.detail = "No UniqueConstraint on post_id — same post could create multiple leads"
        c.fix    = "Add: UniqueConstraint('post_id', name='uq_lead_post_id') to Lead.__table_args__"
    report.add(c)


# ══════════════════════════════════════════════════════════════════════════════
#  RENDER
# ══════════════════════════════════════════════════════════════════════════════

def render(report: AuditReport) -> None:
    ICON = {"PASS": PASS, "WARN": WARN, "FAIL": FAIL}

    print(f"\n{BOLD}{CYAN}{'═'*72}{RESET}")
    print(f"{BOLD}{CYAN}  LEAD-IQ  ·  DAY 1 AFTERNOON AUDIT{RESET}")
    print(f"{BOLD}{CYAN}  DB Lifespan · Storage · Schema · Alembic{RESET}")
    print(f"{BOLD}{CYAN}{'═'*72}{RESET}\n")

    total_score = 0.0
    for task_name, checks in report.by_task().items():
        task_earned = sum(c.score for c in checks)
        task_total  = len(checks)
        pct = int(task_earned / task_total * 100) if task_total else 0
        status_icon = GREEN+"✅"+RESET if pct >= 87 else YELLOW+"⚠️"+RESET if pct >= 50 else RED+"❌"+RESET
        print(f"  {status_icon} {BOLD}{task_name}{RESET}  [{task_earned:.1f}/{task_total}]")
        print(f"  {'─'*68}")
        for c in checks:
            icon = ICON[c.result]
            print(f"    {icon}  #{c.id:<6} {c.name}")
            print(f"             {c.detail}")
            if c.result != "PASS" and c.fix:
                print(f"             {YELLOW}FIX → {c.fix}{RESET}")
        print()
        total_score += task_earned

    earned, total = report.score()
    pct_total = int(earned / total * 100) if total else 0
    bar_filled = int(pct_total / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    color = GREEN if pct_total >= 87 else YELLOW if pct_total >= 60 else RED

    print(f"{BOLD}{CYAN}{'═'*72}{RESET}")
    print(f"  {BOLD}OVERALL SCORE:{RESET}  {color}{earned:.1f}/{total}{RESET}  ({color}{pct_total}%{RESET})")
    print(f"  {color}{bar}{RESET}")
    if pct_total >= 87:
        print(f"  {GREEN}{BOLD}✅ DAY 1 AFTERNOON COMPLETE — Day 2 tasks UNLOCKED{RESET}")
    elif pct_total >= 60:
        print(f"  {YELLOW}{BOLD}⚠️  PARTIAL PASS — Fix FAIL checks before Day 2{RESET}")
    else:
        print(f"  {RED}{BOLD}❌ BLOCKED — Resolve critical failures first{RESET}")

    fails  = [c for c in report.checks if c.result == "FAIL"]
    warns  = [c for c in report.checks if c.result == "WARN"]
    if fails:
        print(f"\n  {RED}{BOLD}🔴 Critical ({len(fails)}):{RESET}")
        for c in fails:
            print(f"    [{c.id}] {c.name}: {c.fix}")
    if warns:
        print(f"\n  {YELLOW}{BOLD}🟡 Warnings ({len(warns)}):{RESET}")
        for c in warns:
            print(f"    [{c.id}] {c.name}")

    print(f"\n{BOLD}{CYAN}{'═'*72}{RESET}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    report = AuditReport()
    audit_task_21(report)
    audit_task_22(report)
    audit_task_23(report)
    audit_task_24(report)
    render(report)

    # Exit code for CI: 0 = pass, 1 = warn, 2 = fail
    earned, total = report.score()
    pct = earned / total * 100 if total else 0
    sys.exit(0 if pct >= 87 else 1 if pct >= 60 else 2)


if __name__ == "__main__":
    main()
