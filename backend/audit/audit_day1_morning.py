#!/usr/bin/env python3
"""
Lead-iq Day 1 Morning Block — Execution Audit Script
Expert Council: Colvin · Karpathy · Kleppmann · Nirav · Amodei
Audits: Task 1.1 (Schema) · Task 1.2 (Analyzer) · Task 1.3 (Prompt)
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from datetime import datetime, UTC

# ANSI Color Palette
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def ok(msg: str) -> str:
    return f"{GREEN}  ✅  {msg}{RESET}"


def fail(msg: str) -> str:
    return f"{RED}  ❌  {msg}{RESET}"


def warn(msg: str) -> str:
    return f"{YELLOW}  ⚠️   {msg}{RESET}"


def info(msg: str) -> str:
    return f"{CYAN}  ℹ️   {msg}{RESET}"


def head(msg: str) -> str:
    return f"\n{BOLD}{BLUE}{'=' * 64}\n  {msg}\n{'=' * 64}{RESET}"


def sub(msg: str) -> str:
    return f"{BOLD}  ── {msg} ──{RESET}"


# ============================================================================
# AUDIT STATE
# ============================================================================
audit_results = {
    "run_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "project_root": None,
    "tasks": {
        "1.1_schema": {"checks": [], "score": 0, "max": 0},
        "1.2_analyzer": {"checks": [], "score": 0, "max": 0},
        "1.3_prompt": {"checks": [], "score": 0, "max": 0},
    },
    "total_score": 0,
    "total_max": 0,
    "verdict": "UNKNOWN",
}


def record(task: str, name: str, passed: bool, detail: str = "", expert: str = "") -> None:
    weight = 1
    audit_results["tasks"][task]["checks"].append(
        {"name": name, "passed": passed, "detail": detail, "expert": expert}
    )
    audit_results["tasks"][task]["max"] += weight
    audit_results["tasks"][task]["score"] += weight if passed else 0


# ============================================================================
# PROJECT ROOT DETECTION
# ============================================================================
def find_project_root() -> Path:
    cwd = Path.cwd()
    for candidate in [cwd] + list(cwd.parents):
        if (candidate / "backend").is_dir():
            return candidate
    return cwd


ROOT = find_project_root()
audit_results["project_root"] = str(ROOT)
BACKEND = ROOT / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))


# ============================================================================
# AST UTILITIES
# ============================================================================
def read_source(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_ast(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def ast_class_names(tree: ast.Module) -> list[str]:
    return [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]


def ast_function_names(tree: ast.Module) -> list[str]:
    return [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def ast_imports(tree: ast.Module) -> list[str]:
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imports += [f"{mod}.{a.name}" for a in node.names]
    return imports


def ast_get_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def ast_class_fields(cls_node: ast.ClassDef) -> list[str]:
    fields = []
    for node in ast.walk(cls_node):
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                fields.append(node.target.id)
    return fields


def ast_method_names(cls_node: ast.ClassDef) -> list[str]:
    return [
        n.name
        for n in ast.walk(cls_node)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def count_mock_indicators(source: str) -> dict:
    patterns = {
        "fake_return": len(re.findall(r"return\s+\{.*fake|fake.*\}", source, re.I)),
        "mock_comment": len(re.findall(r"#.*mock|#.*todo|#.*stub|#.*placeholder", source, re.I)),
        "hardcoded_lead": len(re.findall(r"hardcoded|dummy|sample_lead|test_lead", source, re.I)),
        "sleep_stub": len(re.findall(r"await asyncio\.sleep.*\)\s*$", source, re.M)),
        "none_return": len(re.findall(r"return None\s*#.*mock|#.*mock.*return None", source, re.I)),
    }
    return patterns


# ============================================================================
# TASK 1.1 — SCHEMA AUDIT
# ============================================================================
def audit_task_1_1() -> None:
    print(head("TASK 1.1 — backend/llm/schemas.py  [Expert: Colvin]"))

    schema_path = BACKEND / "llm" / "schemas.py"

    if not schema_path.exists():
        print(fail("File backend/llm/schemas.py not found"))
        for _ in range(17):
            record("1.1_schema", "skipped_check", False, "File missing", "Colvin")
        return

    print(ok("File found: backend/llm/schemas.py"))
    record("1.1_schema", "file_exists", True)

    source = read_source(schema_path)
    tree = parse_ast(source)
    if not tree:
        print(fail("File has syntax errors"))
        record("1.1_schema", "file_parseable", False)
        return
    record("1.1_schema", "file_parseable", True)

    # 2. AnalyzedLead class present
    cls = ast_get_class(tree, "AnalyzedLead")
    exists = cls is not None
    print(ok("AnalyzedLead class found") if exists else fail("AnalyzedLead class NOT found"))
    record("1.1_schema", "class_AnalyzedLead_exists", exists, expert="Colvin")
    if not exists:
        return

    # 3. Inherits from BaseModel
    bases = [
        b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else "?")
        for b in cls.bases
    ]
    inherits = "BaseModel" in bases
    print(ok("Inherits BaseModel") if inherits else fail(f"Bases: {bases} — must include BaseModel"))
    record("1.1_schema", "inherits_BaseModel", inherits, expert="Colvin")

    # 4. Required fields present
    fields = ast_class_fields(cls)
    REQUIRED = [
        "is_opportunity",
        "confidence",
        "intent",
        "urgency",
        "reason",
        "company_name",
        "company_size",
        "industry",
        "contact_name",
        "contact_title",
        "icp_fit_score",
        "outreach_draft",
        "source",
        "source_url",
        "model_used",
        "tokens_used",
        "analyzed_at",
    ]

    print(sub("Required Fields Check"))
    missing_fields = []
    for f in REQUIRED:
        if f in fields:
            print(ok(f"  Field present: {f}"))
        else:
            print(fail(f"  Field MISSING: {f}"))
            missing_fields.append(f)
    record("1.1_schema", "all_required_fields", len(missing_fields) == 0, f"Missing: {missing_fields}" if missing_fields else "All fields present", expert="Colvin")

    # 5. Confidence has ge/le constraints
    confidence_constrained = (
        ("ge=0.0" in source or "ge=0," in source or "ge=0)" in source)
        and ("le=1.0" in source or "le=1," in source or "le=1)" in source)
    )
    print(
        ok("confidence Field(ge=0.0, le=1.0) constraint present")
        if confidence_constrained
        else fail("confidence missing ge/le bounds")
    )
    record("1.1_schema", "confidence_bounded", confidence_constrained, expert="Colvin")

    # 6. Literal types used for intent and urgency
    has_literal = "Literal" in source
    intent_literal = all(v in source for v in ['"buy"', '"evaluate"', '"research"', '"hire"', '"other"'])
    urgency_literal = all(v in source for v in ['"immediate"', '"short_term"', '"long_term"', '"unknown"'])
    lits_ok = has_literal and intent_literal and urgency_literal
    print(
        ok("Literal types for intent + urgency correct")
        if lits_ok
        else fail("intent/urgency must use Literal")
    )
    record("1.1_schema", "literal_intent_urgency", lits_ok, expert="Manning")

    # 7. model_validator present
    has_validator = "model_validator" in source and ("mode='after'" in source or 'mode="after"' in source)
    print(
        ok("model_validator(mode='after') present")
        if has_validator
        else fail("model_validator missing")
    )
    record("1.1_schema", "model_validator_present", has_validator, expert="Colvin")

    # 8. Confidence downgrade logic
    downgrade_logic = (
        ("0.7" in source or "0.70" in source)
        and ("confidence" in source)
        and ("company_name" in source or "contact_name" in source or "raw_excerpt" in source)
    )
    print(
        ok("Confidence downgrade logic (> 0.7 needs evidence) found")
        if downgrade_logic
        else warn("Confidence downgrade rule not found")
    )
    record("1.1_schema", "confidence_downgrade_rule", downgrade_logic, expert="Amodei")

    # 9. extra = "ignore" Config
    has_extra_ignore = (
        'extra = "ignore"' in source or 'extra="ignore"' in source or '"extra": "ignore"' in source
    )
    print(
        ok('Config: extra="ignore" prevents hallucination')
        if has_extra_ignore
        else fail('Config extra="ignore" MISSING')
    )
    record("1.1_schema", "config_extra_ignore", has_extra_ignore, expert="Colvin")

    # 10. Pydantic v2 import
    imports = ast_imports(tree)
    has_pydantic_v2 = any("pydantic" in imp for imp in imports)
    print(
        ok("Pydantic v2 imports detected") if has_pydantic_v2 else fail("No pydantic import found")
    )
    record("1.1_schema", "pydantic_v2_import", has_pydantic_v2, expert="Colvin")

    # 11. india_signals default_factory
    has_india_factory = "india_signals" in source and "default_factory" in source
    print(
        ok("india_signals uses Field(default_factory=list)")
        if has_india_factory
        else warn("india_signals may not have default_factory")
    )
    record("1.1_schema", "india_signals_default_factory", has_india_factory, expert="Colvin")

    # 12. Runtime validation test (check source for model_validate_json)
    has_safe_parse = "model_validate" in source or "model_validate_json" in source
    has_raw_json_load = bool(re.search(r"json\.loads\(", source))
    if has_safe_parse and not has_raw_json_load:
        print(ok("model_validate() used — Colvin's no-raw-json rule respected"))
        record("1.1_schema", "safe_parse_no_json_loads", True, expert="Colvin")
    elif has_raw_json_load:
        print(fail("json.loads() detected — must use model_validate()"))
        record("1.1_schema", "safe_parse_no_json_loads", False, expert="Colvin")
    else:
        print(warn("Parse step may be missing"))
        record("1.1_schema", "safe_parse_no_json_loads", False)

    # 13. Field validators
    has_field_validator = "field_validator" in source
    print(
        ok("field_validator present for intent/urgency")
        if has_field_validator
        else fail("field_validator missing")
    )
    record("1.1_schema", "field_validator_present", has_field_validator, expert="Colvin")


# ============================================================================
# TASK 1.2 — ANALYZER AUDIT
# ============================================================================
def audit_task_1_2() -> None:
    print(head("TASK 1.2 — backend/workers/analyzer.py  [Experts: Kleppmann · Patel · Baker]"))

    analyzer_path = BACKEND / "workers" / "analyzer.py"

    # Check alternative locations
    if not analyzer_path.exists():
        for alt in [BACKEND / "analyzer.py", BACKEND / "llm" / "analyzer.py"]:
            if alt.exists():
                analyzer_path = alt
                print(warn(f"Found at {alt.relative_to(ROOT)} — preferred: backend/workers/analyzer.py"))
                break
        else:
            print(fail("analyzer.py not found in backend/"))
            record("1.2_analyzer", "file_exists", False)
            return

    print(ok(f"File found: {analyzer_path.relative_to(ROOT)}"))
    record("1.2_analyzer", "file_exists", True)

    source = read_source(analyzer_path)
    tree = parse_ast(source)
    if not tree:
        print(fail("analyzer.py has syntax errors"))
        record("1.2_analyzer", "file_parseable", False)
        return
    record("1.2_analyzer", "file_parseable", True)

    # 2. GeminiAnalyzer class
    cls = ast_get_class(tree, "GeminiAnalyzer")
    exists = cls is not None
    print(ok("GeminiAnalyzer class found") if exists else fail("GeminiAnalyzer class NOT found"))
    record("1.2_analyzer", "class_GeminiAnalyzer_exists", exists)
    if not exists:
        return

    methods = ast_method_names(cls)

    # 3. analyze() method exists and is async
    has_analyze = "analyze" in methods
    is_async = any(
        isinstance(n, ast.AsyncFunctionDef) and n.name == "analyze" for n in ast.walk(cls)
    )
    print(ok("analyze() method found") if has_analyze else fail("analyze() method MISSING"))
    print(ok("analyze() is async") if is_async else fail("analyze() is NOT async"))
    record("1.2_analyzer", "method_analyze_exists", has_analyze)
    record("1.2_analyzer", "method_analyze_is_async", is_async, expert="Gil Tene")

    # 4. No mock / fake return paths
    print(sub("Mock Detection Scan"))
    mocks = count_mock_indicators(source)
    total_mocks = sum(mocks.values())
    if total_mocks == 0:
        print(ok("Zero mock indicators found — clean implementation"))
        record("1.2_analyzer", "no_mock_paths", True, expert="Karpathy")
    else:
        for pattern, count in mocks.items():
            if count > 0:
                print(fail(f"  Mock pattern '{pattern}' found {count} time(s)"))
        record("1.2_analyzer", "no_mock_paths", False, f"Mock indicators: {mocks}", expert="Karpathy")

    # 5. Budget check wired
    has_budget = "check_budget" in source or "cost_guard" in source
    print(
        ok("Budget check (check_budget / cost_guard) wired")
        if has_budget
        else fail("Budget gate MISSING")
    )
    record("1.2_analyzer", "budget_check_wired", has_budget, expert="Nirav Patel")

    # 6. Async safety (run_in_executor or to_thread)
    has_executor = "run_in_executor" in source or "to_thread" in source
    has_old_sdk = "import google.generativeai" in source
    has_new_sdk = "from google import genai" in source or "google-genai" in source
    sdk_type = (
        "OLD (google-generativeai)" if has_old_sdk else ("NEW (google-genai)" if has_new_sdk else "UNKNOWN")
    )

    if has_old_sdk and not has_executor:
        print(fail(f"SDK: {sdk_type} — run_in_executor MISSING"))
        record("1.2_analyzer", "async_thread_safety", False, expert="Gil Tene")
    elif has_old_sdk and has_executor:
        print(ok(f"SDK: {sdk_type} — to_thread correctly wraps sync SDK"))
        record("1.2_analyzer", "async_thread_safety", True, expert="Gil Tene")
    elif has_new_sdk:
        print(ok(f"SDK: {sdk_type} — native async, no executor needed"))
        record("1.2_analyzer", "async_thread_safety", True, expert="Gil Tene")
    else:
        print(info("No Gemini SDK import detected"))
        record("1.2_analyzer", "async_thread_safety", False)

    # 7. model_validate used (not json.loads)
    has_safe_parse = "model_validate" in source or "model_validate_json" in source
    has_raw_json_load = bool(re.search(r"json\.loads\(", source))
    if has_safe_parse and not has_raw_json_load:
        print(ok("model_validate() used — Colvin's no-raw-json rule respected"))
        record("1.2_analyzer", "safe_parse_no_json_loads", True, expert="Colvin")
    elif has_raw_json_load:
        print(fail("json.loads() detected — must use model_validate()"))
        record("1.2_analyzer", "safe_parse_no_json_loads", False, expert="Colvin")
    else:
        print(warn("Parse step may be missing"))
        record("1.2_analyzer", "safe_parse_no_json_loads", False)

    # 8. Token accounting to Redis
    has_token_redis = ("incrby" in source.lower() or "incr" in source.lower()) and "token" in source.lower()
    print(
        ok("Redis token accounting (INCRBY) wired")
        if has_token_redis
        else fail("Token accounting MISSING")
    )
    record("1.2_analyzer", "redis_token_accounting", has_token_redis, expert="Nirav Patel")

    # 9. Token key format
    has_daily_key = "gemini:tokens:" in source
    print(
        ok("Daily token key pattern (gemini:tokens:{date}) found")
        if has_daily_key
        else warn("Token key format unclear")
    )
    record("1.2_analyzer", "token_key_format", has_daily_key, expert="Kleppmann")

    # 10. Structured logging
    has_structlog = "structlog" in source
    has_log_call = ("logger.info" in source or "log.info" in source) and "analysis_complete" in source
    print(
        ok("structlog + analysis_complete event logged")
        if (has_structlog and has_log_call)
        else fail("structlog logging missing")
    )
    record("1.2_analyzer", "structlog_logging", has_structlog and has_log_call, expert="Charity Baker")

    # 11. All required log fields
    LOG_FIELDS = ["is_opportunity", "confidence", "intent", "urgency", "tokens_used"]
    missing_log = [f for f in LOG_FIELDS if f not in source]
    print(
        ok(f"All {len(LOG_FIELDS)} required log fields present")
        if not missing_log
        else warn(f"Log fields missing: {missing_log}")
    )
    record("1.2_analyzer", "log_fields_complete", len(missing_log) == 0, f"Missing: {missing_log}", expert="Charity Baker")

    # 12. Error handling returns None
    has_try_except = "try:" in source and "except" in source
    returns_none_err = "return None" in source
    print(
        ok("try/except with return None on failure")
        if (has_try_except and returns_none_err)
        else fail("Error handling incomplete")
    )
    record("1.2_analyzer", "error_handling_returns_none", has_try_except and returns_none_err, expert="Kleppmann")

    # 13. Audit stamp
    has_stamp = "result.source" in source and "result.tokens_used" in source
    print(
        ok("Audit stamp fields (source, tokens_used) set on result")
        if has_stamp
        else fail("Audit stamp missing")
    )
    record("1.2_analyzer", "audit_stamp_on_result", has_stamp, expert="Kleppmann")

    # 14. Heuristic fallback
    has_heuristic = "_heuristic_classify" in methods
    print(
        ok("Heuristic fallback (_heuristic_classify) exists")
        if has_heuristic
        else fail("Heuristic fallback MISSING")
    )
    record("1.2_analyzer", "heuristic_fallback", has_heuristic)


# ============================================================================
# TASK 1.3 — PROMPT ARCHITECTURE AUDIT
# ============================================================================
def audit_task_1_3() -> None:
    print(head("TASK 1.3 — Source Prompts  [Experts: Karpathy · Ng · Amodei]"))

    # Check SOURCE_PROMPTS.py in llm directory
    source_prompts_path = BACKEND / "llm" / "SOURCE_PROMPTS.py"

    if not source_prompts_path.exists():
        print(fail("SOURCE_PROMPTS.py not found in backend/llm/"))
        record("1.3_prompt", "file_exists", False)
        return

    print(ok("File found: SOURCE_PROMPTS.py"))
    record("1.3_prompt", "file_exists", True)

    source = read_source(source_prompts_path)
    tree = parse_ast(source)
    if not tree:
        print(fail("SOURCE_PROMPTS.py has syntax errors"))
        record("1.3_prompt", "file_parseable", False)
        return
    record("1.3_prompt", "file_parseable", True)

    # 2. SOURCE_PROMPTS dict exists
    has_source_prompts = "SOURCE_PROMPTS" in source
    print(ok("SOURCE_PROMPTS dict present") if has_source_prompts else fail("SOURCE_PROMPTS dict missing"))
    record("1.3_prompt", "SOURCE_PROMPTS_dict_exists", has_source_prompts, expert="Karpathy")

    # 3. INDIA_SIGNALS_LOOKUP exists
    has_india_signals = "INDIA_SIGNALS_LOOKUP" in source
    print(
        ok("INDIA_SIGNALS_LOOKUP dict present")
        if has_india_signals
        else fail("INDIA_SIGNALS_LOOKUP dict missing")
    )
    record("1.3_prompt", "INDIA_SIGNALS_LOOKUP_exists", has_india_signals, expert="Geoffrey Moore")

    # 4. All 8 required sources
    REQUIRED_SOURCES = [
        "hacker_news",
        "reddit",
        "github_profile",
        "producthunt",
        "yourstory",
        "tracxn",
        "stackoverflow",
        "telegram",
    ]
    print(sub("Source Coverage (8 required)"))
    missing_sources = []
    for src in REQUIRED_SOURCES:
        if f'"{src}"' in source or f"'{src}'" in source:
            print(ok(f"  Source defined: {src}"))
        else:
            print(fail(f"  Source MISSING: {src}"))
            missing_sources.append(src)
    record("1.3_prompt", "all_8_sources_defined", len(missing_sources) == 0, f"Missing: {missing_sources}", expert="Karpathy")

    # 5. India-specific signals
    INDIA_SIGNALS = ["Pvt Ltd", "crore", "IIT", "GST", "Razorpay", "DPIIT"]
    has_india = sum(1 for s in INDIA_SIGNALS if s in source)
    india_ok = has_india >= 4
    print(
        ok(f"India signals present ({has_india}/{len(INDIA_SIGNALS)} keywords found)")
        if india_ok
        else fail(f"India signals weak ({has_india}/{len(INDIA_SIGNALS)})")
    )
    record(
        "1.3_prompt",
        "india_signals_in_prompt",
        india_ok,
        f"Found {has_india} of {len(INDIA_SIGNALS)} keywords",
        expert="Geoffrey Moore",
    )

    # 6. Conservative bias rule
    CONSERVATIVE_PHRASES = ["missed lead", "false positive", "conservative", "better than", "wastes", "salesperson"]
    has_conservative = any(p.lower() in source.lower() for p in CONSERVATIVE_PHRASES)
    print(
        ok("Conservative bias rule found (missed lead > false positive)")
        if has_conservative
        else fail("Conservative bias rule MISSING")
    )
    record("1.3_prompt", "conservative_bias_rule", has_conservative, expert="Amodei")

    # 7. Confidence scale guide in prompt
    CONF_SCALE = ["0.3", "0.5", "0.7", "0.9"]
    scale_present = sum(1 for c in CONF_SCALE if c in source)
    has_scale = scale_present >= 3
    print(
        ok(f"Confidence scale guide present ({scale_present}/4 anchors)")
        if has_scale
        else warn(f"Confidence scale incomplete ({scale_present}/4)")
    )
    record("1.3_prompt", "confidence_scale_guide", has_scale, expert="Andrew Ng")

    # 8. Email extraction rule
    email_rule = (
        "literally" in source.lower() or "written in text" in source.lower() or "never infer" in source.lower()
    ) and "email" in source.lower()
    print(
        ok("Email extraction rule ('only if literally written') found")
        if email_rule
        else fail("Email rule MISSING")
    )
    record("1.3_prompt", "email_extraction_rule", email_rule, expert="Amodei")

    # 9. Prompt length guard
    prompt_cap = "3000" in source or ":3000" in source or "3000]" in source
    print(
        ok("Text truncation at 3000 chars found")
        if prompt_cap
        else warn("No text truncation found")
    )
    record("1.3_prompt", "prompt_length_cap", prompt_cap, expert="Nirav Patel")

    # 10. Persona definition in prompt
    has_persona = (
        "B2B sales intelligence" in source or "Lead-iq" in source
    ) and "analyst" in source.lower()
    print(
        ok("Persona definition found (B2B sales intelligence analyst)")
        if has_persona
        else fail("Persona missing")
    )
    record("1.3_prompt", "persona_in_prompt", has_persona, expert="Andrew Ng")

    # 11. pain_point exact rule
    pain_rule = ("exact" in source.lower() or "EXACT" in source) and "pain_point" in source
    print(
        ok("pain_point exact-phrase rule found")
        if pain_rule
        else warn("pain_point rule unclear")
    )
    record("1.3_prompt", "pain_point_exact_rule", pain_rule, expert="Karpathy")

    # 12. _build_prompt function exists
    has_build_prompt = "_build_prompt" in source
    print(
        ok("_build_prompt() function exists")
        if has_build_prompt
        else fail("_build_prompt() MISSING")
    )
    record("1.3_prompt", "method_build_prompt_exists", has_build_prompt, expert="Karpathy")


# ============================================================================
# FINAL REPORT
# ============================================================================
def print_final_report() -> int:
    print(head("AUDIT SUMMARY — Day 1 Morning Block"))

    total_score = 0
    total_max = 0
    task_labels = {
        "1.1_schema": "Task 1.1  Schema Design        [Colvin]",
        "1.2_analyzer": "Task 1.2  Analyzer Wiring      [Kleppmann · Patel · Baker]",
        "1.3_prompt": "Task 1.3  Prompt Architecture  [Karpathy · Ng · Amodei]",
    }

    for task_key, label in task_labels.items():
        t = audit_results["tasks"][task_key]
        score = t["score"]
        mx = t["max"]
        pct = int(score / mx * 100) if mx > 0 else 0
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        color = GREEN if pct >= 80 else (YELLOW if pct >= 60 else RED)
        print(f"  {color}{label:<44} [{bar}] {score}/{mx} ({pct}%){RESET}")
        total_score += score
        total_max += mx

    total_pct = int(total_score / total_max * 100) if total_max > 0 else 0
    bar_total = "█" * (total_pct // 5) + "░" * (20 - total_pct // 5)
    color = GREEN if total_pct >= 80 else (YELLOW if total_pct >= 60 else RED)

    print(f"\n  {BOLD}{'─' * 64}{RESET}")
    print(f"  {BOLD}{color}TOTAL MORNING BLOCK SCORE: [{bar_total}] {total_score}/{total_max} ({total_pct}%){RESET}")

    if total_pct == 100:
        verdict = "PERFECT"
        msg = f"\n  {GREEN}{BOLD}PERFECT SCORE — All Day 1 morning gates pass.{RESET}"
    elif total_pct >= 80:
        verdict = "PASS"
        msg = f"\n  {GREEN}{BOLD}PASS — Morning block complete. Fix warnings before afternoon.{RESET}"
    elif total_pct >= 60:
        verdict = "PARTIAL"
        msg = f"\n  {YELLOW}{BOLD}PARTIAL — Core wiring done but gaps remain. Fix ❌ before DB task.{RESET}"
    else:
        verdict = "FAIL"
        msg = f"\n  {RED}{BOLD}FAIL — Critical gaps. Do NOT proceed to Task 1.4 until fixed.{RESET}"

    print(msg)

    # Failure Triage
    all_failures = []
    for task_key, t in audit_results["tasks"].items():
        for c in t["checks"]:
            if not c["passed"]:
                all_failures.append((task_key, c))

    if all_failures:
        print(f"\n  {BOLD}{RED}FAILED CHECKS (fix in order):{RESET}")
        for i, (task, c) in enumerate(all_failures, 1):
            expert = f"  [{c['expert']}]" if c["expert"] else ""
            detail = f" — {c['detail']}" if c["detail"] else ""
            print(f"  {RED}{i:2}. [{task}] {c['name']}{expert}{detail}{RESET}")

    audit_results["total_score"] = total_score
    audit_results["total_max"] = total_max
    audit_results["verdict"] = verdict
    audit_results["pass_rate"] = total_pct

    # Write JSON report
    report_path = ROOT / "audit_day1_morning_report.json"
    with open(report_path, "w") as f:
        json.dump(audit_results, f, indent=2, default=str)
    print(f"\n  {DIM}Full report: {report_path}{RESET}\n")

    return 0 if total_pct >= 80 else 1


# ============================================================================
# ENTRYPOINT
# ============================================================================
if __name__ == "__main__":
    print(f"{BOLD}{CYAN}")
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║        LEAD-IQ DAY 1 MORNING BLOCK AUDIT                 ║")
    print("  ║  Tasks: 1.1 Schema · 1.2 Analyzer · 1.3 Prompt          ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print(f"  Project root: {ROOT}")
    print(f"  Audit time:   {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{RESET}")

    audit_task_1_1()
    audit_task_1_2()
    audit_task_1_3()
    exit_code = print_final_report()
    sys.exit(exit_code)
