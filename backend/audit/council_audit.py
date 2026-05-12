#!/usr/bin/env python3
"""
Lead-iq Council of Skills — Brutal Audit Script v1.0
17 Experts | 6 Guilds | Zero Tolerance Mode
Run from project root: python audit/council_audit.py
"""
import re, json, time
from pathlib import Path
from dataclasses import dataclass, field

R  = "\033[91m"; Y  = "\033[93m"; G  = "\033[92m"; B  = "\033[94m"
M  = "\033[95m"; C  = "\033[96m"; W  = "\033[97m"
DIM= "\033[2m";  RST= "\033[0m";  BOLD="\033[1m"

@dataclass
class Finding:
    severity: str
    expert:   str
    rule:     str
    message:  str
    file:     str = ""
    line:     int = 0
    fix:      str = ""

@dataclass
class GuildScore:
    name:     str
    expert:   str
    score:    int = 0
    max:      int = 0
    findings: list = field(default_factory=list)

ROOT     = Path(".")
findings: list = []
guild_scores: dict = {}

def py_files(directory="backend") -> list:
    d = ROOT / directory
    if not d.exists():
        return []
    return list(d.rglob("*.py"))

def read(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except:
        return ""

def exists(path) -> bool:
    return (ROOT / path).exists()

def find_pattern(pattern, dirs, include="*.py") -> list:
    results = []
    for d in dirs:
        base = ROOT / d
        if not base.exists():
            continue
        for f in base.rglob(include):
            try:
                for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                    if re.search(pattern, line, re.IGNORECASE):
                        results.append((str(f), i, line.strip()))
            except:
                pass
    return results

def count_pattern(pattern, content) -> int:
    return len(re.findall(pattern, content))

def add(sev, expert, rule, message, file_="", line=0, fix=""):
    findings.append(Finding(sev, expert, rule, message, file_, line, fix))

def section(title, expert, emoji="x"):
    print(f"\n{BOLD}{emoji}  {title}{RST}")
    print(f"{DIM}   Inspector: {expert}{RST}")
    print(f"{DIM}   {'-'*62}{RST}")

def check(ok, label, score_obj, pts, sev, expert, rule, message, file_="", line=0, fix=""):
    score_obj.max += pts
    if ok:
        score_obj.score += pts
        print(f"   {G}OK  {label}{RST}")
    else:
        icon = {"CRITICAL": f"{R}CRIT", "HIGH": f"{Y}HIGH",
                "MEDIUM":   f"{B}WARN", "LOW":  f"{DIM}INFO"}.get(sev, f"{Y}WARN")
        print(f"   {icon} {label}{RST}")
        if message:
            print(f"      {DIM}-> {message[:120]}{RST}")
        if file_:
            loc = f"{file_}:{line}" if line else file_
            print(f"      {DIM}FILE: {loc}{RST}")
        if fix:
            print(f"      {C}FIX: {fix[:120]}{RST}")
        add(sev, expert, rule, message, file_, line, fix)
        score_obj.findings.append(rule)
    return ok


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════
print(f"""
{BOLD}{M}
╔═══════════════════════════════════════════════════════════════╗
║       LEAD-IQ COUNCIL OF SKILLS — BRUTAL AUDIT v1.0          ║
║       17 Experts · 7 Guilds · Zero Tolerance Mode            ║
╚═══════════════════════════════════════════════════════════════╝
{RST}""")
print(f"{DIM}  Root: {ROOT.resolve()}{RST}")
print(f"{DIM}  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}{RST}\n")


# ═══════════════════════════════════════════════════════════════
# GUILD 1 — LLM QUALITY (Karpathy + Hamel + Lilian + Simon)
# ═══════════════════════════════════════════════════════════════
g1 = GuildScore("LLM Quality", "Karpathy+Hamel+Lilian+Simon")
guild_scores["g1"] = g1
section("GUILD 1: LLM QUALITY", "Karpathy + Hamel + Lilian + Simon", ">>")

gt_exists = exists("eval/ground_truth.json")
check(gt_exists, "eval/ground_truth.json exists", g1, 4,
      "CRITICAL", "Karpathy", "EVAL_MISSING",
      "No ground truth. You ship blind. Precision is unknown.",
      fix="Create eval/ground_truth.json with 50 hand-labeled leads, 5 sources")

if gt_exists:
    try:
        gt = json.loads(read("eval/ground_truth.json"))
        check(len(gt) >= 50, f"Ground truth >= 50 records (found {len(gt)})", g1, 3,
              "HIGH", "Karpathy", "EVAL_INSUFFICIENT",
              f"Only {len(gt)} records. Need 50 for statistical significance.",
              fix="Add records: 10 per source (tracxn, github, yourstory, producthunt, hacker_news)")
        sources = list(set(r.get("source", "") for r in gt if r.get("source")))
        check(len(sources) >= 4, f"Eval spans {len(sources)}/5 sources", g1, 2,
              "HIGH", "Karpathy", "EVAL_SOURCE_COVERAGE",
              f"Sources covered: {sources}. Missing sources = blind extraction spots.",
              fix="Add ground truth for each of your 7 collector sources")
    except Exception as e:
        check(False, "ground_truth.json is valid JSON", g1, 5,
              "CRITICAL", "Karpathy", "EVAL_CORRUPT",
              f"Malformed JSON: {str(e)[:80]}",
              "eval/ground_truth.json",
              fix="Fix JSON syntax in eval/ground_truth.json")
else:
    g1.max += 5

eval_script = exists("eval/run_eval.py")
check(eval_script, "eval/run_eval.py exists", g1, 4,
      "CRITICAL", "Hamel", "EVAL_SCRIPT_MISSING",
      "No eval runner. Rules without measurement are fiction (Hamel's Law).",
      fix="Create eval/run_eval.py computing precision per field per source")

if eval_script:
    ev = read("eval/run_eval.py")
    check("precision" in ev.lower(), "run_eval.py computes precision (not just pass/fail)", g1, 2,
          "HIGH", "Hamel", "EVAL_NO_PRECISION",
          "Pass/fail is not enough. Hamel requires field-level precision scores.",
          fix="Add: correct / expected for each field, per source")
    check("--source" in ev or "argparse" in ev,
          "run_eval.py has --source flag for isolation", g1, 1,
          "MEDIUM", "Hamel", "EVAL_NO_SOURCE_FLAG",
          "Cannot isolate single source. Debugging requires targeted runs.",
          fix="parser.add_argument('--source', type=str, default=None)")
    check("--quick" in ev, "run_eval.py has --quick flag (no live scraping)", g1, 1,
          "LOW", "Hamel", "EVAL_NO_QUICK_FLAG",
          "No --quick flag. Every eval call hits live scrapers = slow + expensive.",
          fix="Add --quick flag using cached HTML fixture files")

cg_paths = ["backend/llm/cost_guard.py", "backend/services/cost_guard.py"]
cg_exists = any(exists(p) for p in cg_paths)
check(cg_exists, "cost_guard.py exists (GCP budget protection)", g1, 4,
      "CRITICAL", "Simon", "COST_GUARD_MISSING",
      "No budget guard. One runaway loop burns $300 GCP credit silently.",
      fix="Create cost_guard.py: Redis key gemini:tokens:{date} with 2M daily cap")

gemini_svc_paths = ["backend/llm/gemini_service.py", "backend/services/gemini_service.py"]
gemini_svc = next((p for p in gemini_svc_paths if exists(p)), None)
check(gemini_svc is not None, "gemini_service.py exists", g1, 3,
      "CRITICAL", "Lilian", "GEMINI_SERVICE_MISSING",
      "No LLM extraction service.",
      fix="Create backend/llm/gemini_service.py with extract_lead() function")

if gemini_svc:
    gc = read(gemini_svc)
    check("SOURCE_PROMPTS" in gc,
          "SOURCE_PROMPTS dict exists (per-source instructions)", g1, 3,
          "HIGH", "Lilian", "GENERIC_PROMPTS",
          "No per-source prompts. Generic prompt = generic garbage. Lilian's ReAct framework requires role+context+format per source.",
          gemini_svc,
          fix='Add SOURCE_PROMPTS = {"tracxn": "...", "github": "...", ...}')
    prompt_count = len(re.findall(r'"(tracxn|github|yourstory|producthunt|hacker_news|indimart|dpiit|mca21|telegram)"', gc))
    check(prompt_count >= 5, f"SOURCE_PROMPTS covers {prompt_count}/8 sources", g1, 2,
          "HIGH", "Lilian", "SPARSE_SOURCE_PROMPTS",
          f"Only {prompt_count} source prompts. Each source has unique HTML structure.",
          fix="Add prompts for all 8 sources: tracxn, github, yourstory, producthunt, hacker_news, indimart, dpiit, mca21")
    check("langextract" in gc.lower() or "LangExtract" in gc,
          "LangExtract used (source-grounded, no hallucination)", g1, 2,
          "MEDIUM", "Harrison", "NO_LANGEXTRACT",
          "Raw JSON prompting has no source grounding. LangExtract maps fields back to source offsets.",
          gemini_svc,
          fix="pip install langextract; use LangExtract schema-enforced extraction")
    check("circuit_breaker" in gc.lower(),
          "Circuit breaker wired in gemini_service.py", g1, 3,
          "HIGH", "Alex Xu", "GEMINI_NO_CIRCUIT_BREAKER",
          "No circuit breaker in Gemini service. API downtime = silent infinite queue buildup.",
          gemini_svc,
          fix="Wrap generate_content() with: await call_with_breaker(fn, fallback_fn=regex_extract)")

    all_gemini_content = " ".join(read(f) for f in py_files("backend") + py_files("workers"))
    gemini_calls  = count_pattern(r"generate_content\(|embed_content\(|get_embeddings", all_gemini_content)
    budget_checks = count_pattern(r"check_budget\(|cost_guard", all_gemini_content)
    if gemini_calls > 0:
        pct = int(min(100, (budget_checks / gemini_calls) * 100))
        check(pct >= 90, f"{pct}% of Gemini calls guarded by check_budget()", g1, 3,
              "CRITICAL", "Simon", "UNGUARDED_GEMINI_CALLS",
              f"Only {budget_checks}/{gemini_calls} Gemini calls have budget guard.",
              fix="Every generate_content() call must be preceded by: if not await check_budget(est_tokens): use_fallback()")

le_paths = ["backend/models/lead_event.py", "backend/models/leadEvent.py"]
le_exists = any(exists(p) for p in le_paths)
check(le_exists, "LeadEvent model exists (Hamel feedback loop)", g1, 3,
      "HIGH", "Hamel", "NO_FEEDBACK_LOOP",
      "No LeadEvent. User corrections are lost. Zero training data from real usage.",
      fix="Create LeadEvent with: event_type, original_value, corrected_value, time_to_decision")

if le_exists:
    le_content = read(next(p for p in le_paths if exists(p)))
    for fname in ["original_value", "corrected_value", "time_to_decision", "event_type"]:
        check(fname in le_content, f"LeadEvent.{fname} field exists", g1, 1,
              "MEDIUM", "Hamel", f"LEAD_EVENT_NO_{fname.upper()}",
              f"Missing {fname}. This is a labeled training signal lost forever.",
              fix=f"Add {fname} = Column(String, nullable=True) to LeadEvent")

print(f"\n  {BOLD}Guild 1: {g1.score}/{g1.max}{RST}")


# ═══════════════════════════════════════════════════════════════
# GUILD 2 — INFRASTRUCTURE (Alex Xu + Hussein Nasser)
# ═══════════════════════════════════════════════════════════════
g2 = GuildScore("Infrastructure", "Alex Xu + Hussein Nasser")
guild_scores["g2"] = g2
section("GUILD 2: INFRASTRUCTURE", "Alex Xu + Hussein Nasser", ">>")

db_paths = ["backend/shared/db.py", "backend/database.py",
            "backend/shared/database.py", "backend/db.py"]
db_path = next((p for p in db_paths if exists(p)), None)
check(db_path is not None, "Database config file found", g2, 1,
      "CRITICAL", "Hussein", "DB_CONFIG_MISSING",
      "No database configuration file.",
      fix="Create backend/shared/db.py with async engine")

if db_path:
    dbc = read(db_path)
    check("6543" in dbc, "Port 6543 (Supavisor) not 5432 (direct)", g2, 5,
          "CRITICAL", "Hussein", "WRONG_DB_PORT",
          "Port 5432 = direct Postgres = 25 connection limit on Supabase free tier. "
          "Your app will deadlock under any real load.",
          db_path,
          fix="Replace ':5432/' with ':6543/' in DATABASE_URL construction")
    check("NullPool" in dbc, "NullPool configured", g2, 4,
          "CRITICAL", "Hussein", "WRONG_POOL",
          "Without NullPool, SQLAlchemy manages its OWN pool on top of Supavisor = connection explosion.",
          db_path,
          fix="from sqlalchemy.pool import NullPool; engine = create_async_engine(url, poolclass=NullPool)")
    check("statement_cache_size" in dbc, "statement_cache_size=0 set", g2, 3,
          "HIGH", "Hussein", "STATEMENT_CACHE",
          "Transaction pooler mode REQUIRES statement_cache_size=0 or you get "
          "'prepared statement does not exist' errors in production.",
          db_path,
          fix="connect_args={'statement_cache_size': 0, 'prepared_statement_cache_size': 0}")
    check("command_timeout" in dbc, "command_timeout set (no infinite waits)", g2, 2,
          "MEDIUM", "Hussein", "NO_TIMEOUT",
          "No DB timeout. Slow query = hung worker = dead app.",
          fix="connect_args={'command_timeout': 30}")

sync_hits = find_pattern(r"session\.query\b", ["backend"], "*.py")
check(len(sync_hits) == 0, f"No sync session.query() calls (found {len(sync_hits)})", g2, 4,
      "CRITICAL", "Hussein", "SYNC_DB_CALLS",
      f"{len(sync_hits)} synchronous DB calls block the asyncio event loop.",
      fix="Replace session.query(X) with: await db.execute(select(X))")
for f, ln, content in sync_hits[:3]:
    print(f"      {R}  -> {f}:{ln}: {content[:80]}{RST}")

celery_paths = ["celery_config.py", "backend/workers/celery_app.py", "backend/celery.py"]
celery_path = next((p for p in celery_paths if exists(p)), None)
if celery_path:
    cc = read(celery_path)
    check("concurrency" in cc.lower(), "CELERY_WORKER_CONCURRENCY explicitly set", g2, 3,
          "HIGH", "Hussein", "CELERY_DEFAULT_CONCURRENCY",
          "Default Celery concurrency = 4 x CPU. Exhausts all 25 Supabase connections instantly.",
          celery_path,
          fix="CELERY_WORKER_CONCURRENCY = 3")
    check("prefetch" in cc.lower(), "CELERY_WORKER_PREFETCH_MULTIPLIER=1", g2, 2,
          "HIGH", "Hussein", "CELERY_PREFETCH",
          "Default prefetch=4 means workers hoard 4 tasks. Long-running extraction blocks queue.",
          fix="CELERY_WORKER_PREFETCH_MULTIPLIER = 1")
    check("acks_late" in cc.lower(), "CELERY_ACKS_LATE=True", g2, 2,
          "HIGH", "Hussein", "CELERY_EARLY_ACK",
          "Early ack = task marked done before completing. Worker crash = silent data loss.",
          fix="CELERY_ACKS_LATE = True")

cb_paths = ["backend/llm/circuit_breaker.py", "backend/workers/circuit_breaker.py",
            "backend/services/circuit_breaker.py"]
cb_exists = any(exists(p) for p in cb_paths)
check(cb_exists, "circuit_breaker.py exists", g2, 4,
      "CRITICAL", "Alex Xu", "NO_CIRCUIT_BREAKER",
      "No circuit breaker. Gemini/Hunter down = tasks pile up infinitely. App dies silently.",
      fix="Create circuit_breaker.py: CLOSED/OPEN/HALF_OPEN states in Redis, shared across workers")

dlq_paths = ["backend/workers/dlq.py", "backend/services/dlq.py"]
dlq_exists = any(exists(p) for p in dlq_paths)
check(dlq_exists, "dlq.py exists (Dead Letter Queue)", g2, 4,
      "CRITICAL", "Alex Xu", "NO_DLQ",
      "No DLQ. Failed tasks vanish. You have no visibility into what broke in production.",
      fix="Create dlq.py using Redis Streams XADD to capture all Celery task failures")

rate_limit = bool(find_pattern(r"@limiter\.limit|slowapi|RateLimiter", ["backend"], "*.py"))
check(rate_limit, "Rate limits on endpoints (SlowAPI)", g2, 3,
      "HIGH", "Alex Xu", "NO_RATE_LIMITS",
      "No rate limits. Anyone can POST /api/run-miner 10000 times and burn your GCP budget.",
      fix="@limiter.limit('5/minute') on all collector trigger endpoints")

health = bool(find_pattern(r'route.*health|path.*health|"/health"', ["backend"], "*.py"))
check(health, "/health endpoint with dependency checks", g2, 2,
      "MEDIUM", "Simon", "NO_HEALTH_ENDPOINT",
      "No health endpoint. You cannot verify system state in production without one.",
      fix="GET /health checking: postgres, redis, gemini circuit state, celery workers, DLQ stats")

print(f"\n  {BOLD}Guild 2: {g2.score}/{g2.max}{RST}")


# ═══════════════════════════════════════════════════════════════
# GUILD 3 — DB INTERNALS (Arpit Bhayani)
# ═══════════════════════════════════════════════════════════════
g3 = GuildScore("DB Internals", "Arpit Bhayani")
guild_scores["g3"] = g3
section("GUILD 3: DATABASE INTERNALS", "Arpit Bhayani", ">>")

mig_dir = next((p for p in ["migrations/versions", "alembic/versions"] if exists(p)), None)
check(mig_dir is not None, "Alembic migrations directory exists", g3, 2,
      "HIGH", "Arpit", "NO_MIGRATIONS",
      "No migration history. Schema changes are manual and untraceable.",
      fix="alembic init migrations && alembic revision --autogenerate -m 'initial'")

if mig_dir:
    mig_files = list((ROOT / mig_dir).glob("*.py"))
    check(len(mig_files) >= 3, f"{len(mig_files)} migration files (need >=3)", g3, 2,
          "HIGH", "Arpit", "INSUFFICIENT_MIGRATIONS",
          f"Only {len(mig_files)} migrations. Missing: Lead unified, ICP, LeadEvent, embedding.",
          fix="Separate migrations for: base schema, ICP table, LeadEvent, vector extension")

    mc = " ".join(read(f) for f in mig_files)
    check("vector" in mc.lower() or "pgvector" in mc.lower(),
          "pgvector extension installed in migration", g3, 4,
          "CRITICAL", "Arpit", "NO_PGVECTOR",
          "pgvector not installed via migration. ICP semantic matching will fail at runtime.",
          fix="op.execute(\"CREATE EXTENSION IF NOT EXISTS vector\") in a migration")
    check("hnsw" in mc.lower(), "HNSW index (not IVFFlat)", g3, 4,
          "HIGH", "Arpit", "NO_HNSW",
          "No HNSW index. IVFFlat degrades after bulk inserts — query precision drops silently.",
          fix="CREATE INDEX USING hnsw(embedding vector_cosine_ops) WITH (m=16, ef_construction=64)")
    check("ivfflat" not in mc.lower(), "No deprecated IVFFlat index in use", g3, 2,
          "MEDIUM", "Arpit", "IVFFLAT_FOUND",
          "IVFFlat found. Replace with HNSW — better recall, no degradation on inserts.",
          fix="DROP old IVFFlat index; CREATE new HNSW index")

    for idx_sig, idx_desc, pts in [
        (r"status.*created_at|created_at.*status", "(status, created_at)", 3),
        (r"icp_score.*status|status.*icp_score",   "(icp_score, status)", 2),
        (r"company_domain",                         "company_domain",      2),
        (r"final_score",                            "final_score",         1),
    ]:
        check(bool(re.search(idx_sig, mc, re.I)),
              f"Composite index: {idx_desc}", g3, pts,
              "HIGH" if pts >= 2 else "MEDIUM", "Arpit",
              f"NO_INDEX_{idx_desc.replace('(','').replace(')','').replace(', ','_').upper()}",
              f"Missing {idx_desc} index. Full table scans on every dashboard query.",
              fix=f"CREATE INDEX CONCURRENTLY ON leads {idx_desc}")

    check(bool(re.search(r"CHECK.*confidence|confidence.*CHECK", mc, re.I)),
          "CHECK constraint on confidence (0.0-1.0)", g3, 2,
          "MEDIUM", "Arpit", "NO_CONFIDENCE_CONSTRAINT",
          "No range constraint. confidence=99 can silently enter DB and corrupt scoring.",
          fix="ADD CONSTRAINT ck_confidence CHECK (confidence BETWEEN 0.0 AND 1.0)")

dedup_path = next((p for p in ["backend/services/dedup_service.py",
                                "backend/services/dedup.py"] if exists(p)), None)
if dedup_path:
    dc = read(dedup_path)
    lines = dc.splitlines()
    n1_found = False
    for i, line in enumerate(lines):
        if re.search(r"for .+ in .+:", line):
            context = "\n".join(lines[i:min(i+5, len(lines))])
            if re.search(r"await db\.|await session\.", context):
                n1_found = True
                break
    check(not n1_found, "No N+1 queries in dedup_service.py", g3, 4,
          "HIGH", "Arpit", "N_PLUS_ONE",
          "Loop with per-item DB query detected. 100 leads = 200 DB round-trips.",
          dedup_path,
          fix="Batch: SELECT WHERE id IN (...) once, then merge in memory using dict lookups")

print(f"\n  {BOLD}Guild 3: {g3.score}/{g3.max}{RST}")


# ═══════════════════════════════════════════════════════════════
# GUILD 4 — ARCHITECTURE (Fowler + Gaurav + Neal Ford + Mark Richards)
# ═══════════════════════════════════════════════════════════════
g4 = GuildScore("Architecture", "Fowler+Gaurav+NealFord+MarkRichards")
guild_scores["g4"] = g4
section("GUILD 4: ARCHITECTURE", "Fowler + Gaurav Sen + Neal Ford + Mark Richards", ">>")

emitter_paths = ["backend/events/emitter.py", "backend/events.py", "backend/services/events.py"]
em_exists = any(exists(p) for p in emitter_paths)
check(em_exists, "Domain event emitter exists (Fowler)", g4, 3,
      "HIGH", "Fowler", "NO_DOMAIN_EVENTS",
      "No domain events. Lead state changes are mutations. History is permanently lost.",
      fix="Create emitter.py: emit('lead_created', payload) -> Redis XADD stream")

if em_exists:
    em_content = read(next(p for p in emitter_paths if exists(p)))
    for ev in ["lead_created", "lead_enriched", "lead_scored"]:
        check(ev in em_content.lower(), f"Domain event '{ev}' defined", g4, 1,
              "MEDIUM", "Fowler", f"MISSING_EVENT_{ev.upper()}",
              f"'{ev}' event undefined. This transition has no audit trail or replay capability.",
              fix=f"Add '{ev}' to STREAMS dict in emitter.py")

all_tasks = " ".join(read(f) for f in py_files("backend/workers") + py_files("workers"))
pubsub_in_tasks = bool(re.search(r"\.publish\(", all_tasks))
check(not pubsub_in_tasks, "Celery tasks don't call redis.publish() (Gaurav's rule)", g4, 3,
      "HIGH", "Gaurav Sen", "CELERY_PUBSUB_MIXED",
      "redis.publish() inside Celery tasks mixes work queue with event bus. "
      "Events are permanently lost if no subscriber is active.",
      fix="Remove .publish() from tasks. Use emitter.emit() from API layer only.")

check(bool(re.search(r"xadd|XADD", em_content if em_exists else "")),
      "Redis Streams XADD used (persistent, not ephemeral pub/sub)", g4, 3,
      "HIGH", "Gaurav Sen", "PUBSUB_NOT_STREAMS",
      "Pub/Sub messages vanish if no listener. Redis Streams persist until consumed.",
      fix="r.xadd('stream_name', data) — not r.publish('channel', data)")

ff_paths = ["backend/services/feature_flags.py", "backend/feature_flags.py"]
ff_exists = any(exists(p) for p in ff_paths)
check(ff_exists, "Feature flags for actors (Neal Ford)", g4, 3,
      "HIGH", "Neal Ford", "NO_FEATURE_FLAGS",
      "No feature flags. Breaking actor requires full redeploy to disable. "
      "Neal Ford: every independently-breakable unit needs independent kill switch.",
      fix="Create feature_flags.py: is_actor_enabled('tracxn') checks Redis toggle")

if ff_exists:
    ff_content = read(next(p for p in ff_paths if exists(p)))
    covered = sum(1 for a in ["tracxn", "dpiit", "mca21", "telegram", "github"]
                  if a in ff_content.lower())
    check(covered >= 4, f"Feature flags cover {covered}/5 actors", g4, 2,
          "MEDIUM", "Neal Ford", "INCOMPLETE_FLAGS",
          f"Only {covered} actors flaggable.",
          fix="Add all 7 actors to ACTOR_FLAGS dict")

arch_tests = list((ROOT / "tests" / "architecture").glob("*.py")) if exists("tests/architecture") else []
check(len(arch_tests) > 0, "Architectural fitness tests exist (Mark Richards)", g4, 4,
      "HIGH", "Mark Richards", "NO_FITNESS_FUNCTIONS",
      "CLAUDE.md rules enforced by memory, not machines. They WILL be violated at 2 AM.",
      "tests/architecture/",
      fix="Create tests/architecture/test_fitness_functions.py with 6 automated checks")

if arch_tests:
    aac = " ".join(read(f) for f in arch_tests)
    for fn, desc in [("no_sync_db", "sync DB check"),
                     ("no_print", "print() check"),
                     ("rate_limit", "rate limit check"),
                     ("hardcoded", "secrets check"),
                     ("cost_guard", "budget guard check"),
                     ("lead_schema", "schema contract check")]:
        check(fn in aac.lower(), f"Fitness fn: {desc}", g4, 1,
              "MEDIUM", "Mark Richards", f"NO_FITNESS_{fn.upper()}",
              f"'{desc}' not automated. Rule without CI enforcement does not exist.",
              fix=f"Add test_{fn}() to test_fitness_functions.py")

ci_exists = any(exists(p) for p in [".github/workflows/ci.yml",
                                     ".github/workflows/test.yml"])
check(ci_exists, "GitHub Actions CI pipeline exists", g4, 3,
      "HIGH", "Mark Richards", "NO_CI",
      "No CI pipeline. Fitness functions not running in CI = not running at all.",
      fix="Create .github/workflows/ci.yml: pytest tests/architecture/ on every push")

print(f"\n  {BOLD}Guild 4: {g4.score}/{g4.max}{RST}")


# ═══════════════════════════════════════════════════════════════
# GUILD 5 — SECURITY (Zero Tolerance)
# ═══════════════════════════════════════════════════════════════
g5 = GuildScore("Security", "OWASP + Council")
guild_scores["g5"] = g5
section("GUILD 5: SECURITY", "OWASP Top 10 + Council Mandate", ">>")

SECRET_PATTERNS = [
    (r"sk-ant-api[0-9A-Za-z_-]+",                         "Anthropic API key"),
    (r"AIzaSy[0-9A-Za-z_-]{20,}",                         "Google API key"),
    (r"ghp_[0-9A-Za-z]{30,}",                             "GitHub Personal Access Token"),
    (r"AKIA[0-9A-Z]{16}",                                  "AWS Access Key ID"),
    (r"(?i)password\s*=\s*[\"'][^$\{][^\"']{4,}[\"']",    "Hardcoded password"),
    (r"(?i)api_key\s*=\s*[\"'][a-z0-9_\-]{16,}[\"']",     "Hardcoded API key"),
]

all_src = (py_files("backend") + py_files("workers") +
           list(ROOT.glob("*.py")) +
           (list((ROOT/"frontend").rglob("*.ts")) if exists("frontend") else py_files("backend")))

for pattern, desc in SECRET_PATTERNS:
    hits = []
    for fp in all_src:
        if re.search(pattern, read(fp)):
            hits.append(str(fp))
    check(len(hits) == 0, f"No {desc} hardcoded", g5, 5,
          "CRITICAL", "Security", f"SECRET_{desc.replace(' ','_').upper()}",
          f"Exposed in: {hits}",
          fix="Remove immediately. Rotate key. Use os.environ['KEY_NAME']")

gitignore = read(".gitignore")
check(".env" in gitignore, ".env in .gitignore", g5, 4,
      "CRITICAL", "Security", "ENV_NOT_IGNORED",
      ".env not ignored. Credentials will be committed.",
      ".gitignore",
      fix='echo ".env" >> .gitignore && echo ".env.*" >> .gitignore')

config_path = next((p for p in ["backend/config.py", "backend/core/config.py"] if exists(p)), None)
if config_path:
    cfg = read(config_path)
    bad_jwt = bool(re.search(
        r'JWT_SECRET\s*=\s*["\'][^$\{][^"\']{0,40}["\']|'
        r'getenv\(["\']JWT[^"\']*["\'],\s*["\']',
        cfg, re.I))
    check(not bad_jwt, "JWT_SECRET has NO default value (hard fail if missing)", g5, 5,
          "CRITICAL", "Security", "JWT_DEFAULT",
          "Hardcoded/default JWT secret. Anyone can forge tokens with known secret.",
          config_path,
          fix="JWT_SECRET = os.environ['JWT_SECRET']  # no fallback — crash on missing is correct")

routes_all = " ".join(read(f) for f in py_files("backend"))
unauth = re.findall(r'@router\.post\(["\'][^"\']*run[^"\']*["\']', routes_all)
check(len(unauth) == 0, f"No unprotected /run-* endpoints (found {len(unauth)})", g5, 5,
      "CRITICAL", "Security", "UNPROTECTED_ENDPOINTS",
      "/run-miner or /run-ai without auth: anyone can trigger Gemini and burn your credit.",
      fix="Add Depends(get_current_user) to every /run-* route")

fstring_sql = find_pattern(
    r'f["\'].*(?:SELECT|INSERT|UPDATE|DELETE|WHERE)', ["backend", "workers"], "*.py")
check(len(fstring_sql) == 0, f"No f-string SQL (injection risk — found {len(fstring_sql)})", g5, 4,
      "CRITICAL", "Security", "SQL_INJECTION",
      "F-string SQL = SQL injection vulnerability.",
      fix="Use SQLAlchemy ORM or parameterized text(query).bindparams()")
for f, ln, c in fstring_sql[:2]:
    print(f"      {R}  -> {f}:{ln}: {c[:80]}{RST}")

cors_wildcard = bool(re.search(r'allow_origins.*[\[\(].*["\*]["\'])', routes_all, re.I))
check(not cors_wildcard, "CORS not wildcard '*'", g5, 3,
      "HIGH", "Security", "CORS_WILDCARD",
      "CORS wildcard in production = any website can make authenticated requests as your users.",
      fix="allow_origins=['https://your-app.vercel.app'] — never '*' in production")

mw_path = "frontend/middleware.ts"
if exists(mw_path):
    mw = read(mw_path)
    check("jwtVerify" in mw or ("verify" in mw.lower() and "jwt" in mw.lower()),
          "middleware.ts verifies JWT cryptographic signature", g5, 4,
          "CRITICAL", "Security", "MIDDLEWARE_NO_VERIFY",
          "Middleware checks cookie existence but NOT cryptographic validity. "
          "Any string in session cookie = authenticated.",
          mw_path,
          fix="const { payload } = await jwtVerify(token, JWT_SECRET) from 'jose'")

print(f"\n  {BOLD}Guild 5: {g5.score}/{g5.max}{RST}")


# ═══════════════════════════════════════════════════════════════
# GUILD 6 — DATA MOAT (Kunal Shah + swyx)
# ═══════════════════════════════════════════════════════════════
g6 = GuildScore("Data Moat", "Kunal Shah + swyx")
guild_scores["g6"] = g6
section("GUILD 6: DATA MOAT", "Kunal Shah + swyx + Eugene Yan", ">>")

ACTORS = {
    "dpiit":       ("workers/dpiit-actor",       "DPIIT Startup India — India moat"),
    "tracxn":      ("workers/tracxn-actor",       "Tracxn — India startup DB"),
    "mca21":       ("workers/mca21-actor",        "MCA21 ROC filings — legal entity"),
    "telegram":    ("workers/telegram-actor",     "Telegram — real-time signals"),
    "github":      ("workers/github-actor",       "GitHub — tech + founder signals"),
    "producthunt": ("workers/producthunt-actor",  "ProductHunt — product launches"),
    "hn":          ("workers/hn-actor",           "HackerNews — hiring signal"),
}

for actor_id, (actor_path, desc) in ACTORS.items():
    actor_main = f"{actor_path}/main.py"
    a_exists = exists(actor_main)
    if a_exists:
        ac = read(actor_main)
        is_stub = len(ac.strip()) < 300 or ac.count("pass") > 3 or "return None" in ac[:600]
    else:
        is_stub = True
    check(a_exists and not is_stub, f"Actor '{actor_id}': {desc}", g6, 2,
          "HIGH" if actor_id in ["dpiit", "tracxn", "mca21"] else "MEDIUM",
          "Kunal Shah", f"ACTOR_{actor_id.upper()}",
          f"Actor '{actor_id}' {'missing' if not a_exists else 'is stub/empty'}.",
          fix=f"Implement workers/{actor_id}-actor/main.py with full Crawlee + LangExtract logic")

lead_classes = find_pattern(r"^class Lead\b", ["backend"], "*.py")
check(len(lead_classes) <= 1, f"Single Lead model (found {len(lead_classes)})", g6, 5,
      "CRITICAL", "Council", "DUPLICATE_LEAD_MODELS",
      f"Found {len(lead_classes)} Lead class definitions. Conflicting schemas = silent data corruption.",
      fix="Consolidate to single backend/models/lead.py with all fields merged")

for f, ln, _ in lead_classes:
    print(f"      {Y}  -> Lead class at {f}:{ln}{RST}")

lm_content = " ".join(read(f) for f in py_files("backend/models"))
check("embedding" in lm_content and ("Vector" in lm_content or "vector" in lm_content),
      "Lead.embedding Vector(768) column exists", g6, 4,
      "CRITICAL", "Eugene Yan", "NO_EMBEDDING",
      "No embedding column. ICP two-tower matching is impossible without lead embeddings.",
      fix="embedding = Column(Vector(768), nullable=True)  # requires pgvector extension")

conf_path = next((p for p in ["backend/services/confidence.py",
                               "backend/llm/confidence.py"] if exists(p)), None)
check(conf_path is not None, "confidence.py with SOURCE_TRUST registry", g6, 3,
      "HIGH", "Karpathy", "NO_CONFIDENCE",
      "No confidence scoring. All leads have equal trust regardless of source quality.",
      fix="Create confidence.py: SOURCE_TRUST = {'github_api': 0.95, 'indimart': 0.50, ...}")

if conf_path:
    cc = read(conf_path)
    india_covered = sum(1 for s in ["dpiit", "mca21", "gst", "udyam"] if s in cc.lower())
    check(india_covered >= 2, f"India trust signals in confidence.py ({india_covered}/4)", g6, 2,
          "MEDIUM", "Kunal Shah", "NO_INDIA_SIGNALS",
          "India-specific verification signals absent from confidence formula. "
          "DPIIT/GST/Udyam are YOUR moat — Apollo.io doesn't have these.",
          fix="Add INDIA_TRUST_BONUSES: dpiit_recognized+0.15, gst_verified+0.10, mca21_active+0.12")

im_path = next((p for p in ["backend/services/intent_monitor.py",
                              "backend/workers/intent_monitor.py"] if exists(p)), None)
if im_path:
    im = read(im_path)
    check(len(im) > 400 and "pass" not in im[100:400],
          "intent_monitor.py is implemented (not a stub)", g6, 3,
          "HIGH", "swyx", "INTENT_MONITOR_STUB",
          "intent_monitor.py exists but is an empty stub. Feature is non-functional.",
          im_path,
          fix="Implement: NewsAPI check + GitHub activity signal + Celery beat every 30 min")
else:
    check(False, "intent_monitor.py exists", g6, 3,
          "HIGH", "swyx", "NO_INTENT_MONITOR",
          "No intent monitor. Leads go stale. Temporal decay signals not collected.",
          fix="Create intent_monitor.py with quota-guarded API checks + Redis Streams emit")

print(f"\n  {BOLD}Guild 6: {g6.score}/{g6.max}{RST}")


# ═══════════════════════════════════════════════════════════════
# GUILD 7 — CODE QUALITY (Universal)
# ═══════════════════════════════════════════════════════════════
g7 = GuildScore("Code Quality", "All Experts")
guild_scores["g7"] = g7
section("GUILD 7: CODE QUALITY", "All Council Members", ">>")

print_hits = find_pattern(r"^\s*print\(", ["backend", "workers"], "*.py")
print_hits = [(f, ln, c) for f, ln, c in print_hits
              if "test_" not in f and not c.strip().startswith("#")]
check(len(print_hits) == 0, f"No print() in production code (found {len(print_hits)})", g7, 3,
      "HIGH", "Simon", "PRINT_STATEMENTS",
      f"{len(print_hits)} print() calls in production. Use structlog for machine-readable logs.",
      fix="logger = structlog.get_logger(); logger.info('event', key=val)")
for f, ln, c in print_hits[:3]:
    print(f"      {Y}  -> {f}:{ln}: {c[:80]}{RST}")

structlog_hits = find_pattern(r"import structlog|from structlog", ["backend"], "*.py")
check(len(structlog_hits) > 0, "structlog used for structured logging", g7, 2,
      "MEDIUM", "Simon", "NO_STRUCTLOG",
      "No structlog. Standard logging gives you unstructured strings, not searchable JSON.",
      fix="pip install structlog; logger = structlog.get_logger()")

schema_dirs = ["backend/schemas", "backend/api/schemas"]
schema_files = sum(len(list((ROOT/d).glob("*.py"))) for d in schema_dirs if exists(d))
check(schema_files > 0, f"Pydantic v2 schemas exist ({schema_files} files)", g7, 2,
      "HIGH", "Council", "NO_SCHEMAS",
      "No input validation schemas. Raw dicts passed to DB = no type safety.",
      fix="Create backend/schemas/lead.py with LeadCreate(BaseModel), LeadRead, LeadUpdate")

test_count = len(list(ROOT.rglob("test_*.py")))
check(test_count >= 5, f"Test files exist ({test_count} found)", g7, 3,
      "HIGH", "Mark Richards", "INSUFFICIENT_TESTS",
      f"Only {test_count} test files. Fitness functions need a test infrastructure.",
      fix="Create tests/routes/, tests/services/, tests/architecture/ with minimum 5 test files")

sentry_used = bool(find_pattern(r"sentry_sdk|SENTRY_DSN", ["backend"], "*.py"))
check(sentry_used, "Sentry error tracking configured", g7, 2,
      "MEDIUM", "Simon", "NO_SENTRY",
      "No Sentry. Production errors are completely invisible.",
      fix="sentry_sdk.init(dsn=os.environ['SENTRY_DSN'], traces_sample_rate=0.1)")

env_example = exists(".env.example")
check(env_example, ".env.example exists (all vars documented)", g7, 1,
      "LOW", "Simon", "NO_ENV_EXAMPLE",
      "No .env.example. New developers don't know what environment variables are required.",
      fix="Create .env.example with all var names (no values) as documentation")

print(f"\n  {BOLD}Guild 7: {g7.score}/{g7.max}{RST}")


# ═══════════════════════════════════════════════════════════════
# FINAL VERDICT
# ═══════════════════════════════════════════════════════════════
print(f"""
{BOLD}{M}
╔═══════════════════════════════════════════════════════════════╗
║                    FINAL AUDIT VERDICT                       ║
╚═══════════════════════════════════════════════════════════════╝{RST}
""")

all_guilds = [g1, g2, g3, g4, g5, g6, g7]
total      = sum(g.score for g in all_guilds)
total_max  = sum(g.max   for g in all_guilds)
pct        = int(total / total_max * 100) if total_max else 0
grade_col  = G if pct >= 75 else (Y if pct >= 50 else R)

GUILD_LABELS = [
    ">> LLM Quality   (Karpathy+Hamel+Lilian+Simon)",
    ">> Infrastructure (Alex Xu + Hussein Nasser)",
    ">> DB Internals   (Arpit Bhayani)",
    ">> Architecture   (Fowler+Gaurav+Neal+Richards)",
    ">> Security       (Zero Tolerance)",
    ">> Data Moat      (Kunal Shah + swyx)",
    ">> Code Quality   (All Experts)",
]

print(f"  {'Guild':<50} Score  Max   %    Bar")
print(f"  {'-'*80}")
for g, label in zip(all_guilds, GUILD_LABELS, strict=True):
    p    = int(g.score / g.max * 100) if g.max else 0
    bar  = "#" * int(p/5) + "-" * (20 - int(p/5))
    col  = G if p >= 75 else (Y if p >= 50 else R)
    print(f"  {label:<50} {g.score:>3}/{g.max:<3}  {col}{p:>3}%  {bar}{RST}")

print(f"  {'-'*80}")
print(f"  {'TOTAL':<50} {BOLD}{grade_col}{total:>3}/{total_max:<3}  {pct:>3}%{RST}")

grade = ("WORLD-CLASS (90+)"     if pct >= 90 else
         "PRODUCTION-READY"      if pct >= 75 else
         "FUNCTIONAL MVP"        if pct >= 60 else
         "PROTOTYPE — FRAGILE"   if pct >= 45 else
         "NOT DEPLOYABLE")
print(f"\n  {BOLD}GRADE: {grade_col}{grade}{RST}\n")

crits = [f for f in findings if f.severity == "CRITICAL"]
highs = [f for f in findings if f.severity == "HIGH"]
meds  = [f for f in findings if f.severity == "MEDIUM"]
lows  = [f for f in findings if f.severity == "LOW"]
print(f"  {R}CRITICAL: {len(crits):>3}{RST}  "
      f"{Y}HIGH: {len(highs):>3}{RST}  "
      f"{B}MEDIUM: {len(meds):>3}{RST}  "
      f"{DIM}LOW: {len(lows):>3}{RST}\n")

if crits:
    print(f"{BOLD}{R}  CRITICAL FINDINGS — FIX BEFORE ANYTHING ELSE:{RST}")
    for i, f in enumerate(crits, 1):
        print(f"  {R}{i:>2}. [{f.expert}] {f.rule}{RST}")
        print(f"      {DIM}{f.message[:100]}{RST}")
        if f.fix:
            print(f"      {C}FIX: {f.fix[:100]}{RST}")

print(f"\n{BOLD}{G}  HIGHEST ROI FIXES (points per minute):{RST}")
roi = [
    ("Hussein: port 6543 + NullPool + statement_cache",  "+12 pts", "5 min",   "backend/shared/db.py"),
    ("Mark Richards: 6 fitness fns in CI",               "+10 pts", "60 min",  "tests/architecture/"),
    ("Arpit: HNSW migration + composite indexes",        "+8 pts",  "30 min",  "migrations/versions/"),
    ("Alex Xu: circuit_breaker.py + dlq.py",             "+8 pts",  "45 min",  "backend/llm/ + workers/"),
    ("Karpathy: eval/ground_truth.json + run_eval.py",   "+9 pts",  "90 min",  "eval/"),
]
for fix, pts, tmin, loc in roi:
    print(f"  {G}>{RST} {fix:<50} {Y}{pts}{RST}  {DIM}{tmin:>8}  {loc}{RST}")

# Save JSON report
report = {
    "audit_date": time.strftime("%Y-%m-%d %H:%M:%S"),
    "total": total, "max": total_max, "pct": pct, "grade": grade,
    "guilds": {g.name: {"score": g.score, "max": g.max,
                        "pct": int(g.score/g.max*100) if g.max else 0}
               for g in all_guilds},
    "summary": {"critical": len(crits), "high": len(highs),
                "medium": len(meds), "low": len(lows)},
    "findings": [{"sev": f.severity, "expert": f.expert, "rule": f.rule,
                  "msg": f.message, "file": f.file, "fix": f.fix}
                 for f in findings],
}

try:
    with open("audit_report.json", "w") as fp:
        json.dump(report, fp, indent=2)
    print(f"\n  {DIM}Report saved: audit_report.json{RST}")
except Exception as e:
    print(f"\n  {Y}Could not save report: {e}{RST}")

print(f"""
{DIM}  Run again after each session to track progress.
  Target: 75+ before beta | 90+ before paid users.
  Council Verdict: {pct}% — {grade}{RST}
""")
