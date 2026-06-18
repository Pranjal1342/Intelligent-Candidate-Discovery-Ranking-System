# Redrob Hackathon — Candidate Ranking System

**Team:** Production-ready submission for the Intelligent Candidate Discovery & Ranking Challenge.

---

## One-Command Reproduction

```bash
docker build -t redrob-ranker .
docker run --rm --network none \
  -v $(pwd)/candidates.jsonl:/app/candidates.jsonl \
  -v $(pwd)/out:/app/out \
  redrob-ranker
# Output: ./out/submission.csv
```

That single `docker run` command runs the **full pipeline** (precompute + rank + validate) with zero network access and produces a valid `submission.csv`.

---

## Setup (Without Docker)

### Requirements
- Python 3.11
- CPU-only (no GPU required)
- ≥ 16 GB RAM

```bash
# 1. Create virtualenv
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. Install dependencies (all pinned)
pip install -r requirements.txt

# 3. Copy data file
# (skill_aliases.json is already in data/)
```

### Option A: Running the Full Pipeline (Single-Command Shortcut)
We provide an automated, cross-platform python orchestration script that runs the entire end-to-end pipeline (precomputation, ranking, and validation) in order. It halts immediately and prints error output if any step exits non-zero:

```bash
python scripts/run_full_pipeline.py --candidates ./candidates.jsonl --out ./submission.csv
```

*Note on caching:* This script automatically checks if precomputed artifacts under `precomputed/` already exist and are newer than `candidates.jsonl`. If they are, it skips the expensive precomputation stage (Step 1) to optimize runtime. To override this cache check and force a rebuild anyway, use the `--force-precompute` flag:

```bash
python scripts/run_full_pipeline.py --candidates ./candidates.jsonl --out ./submission.csv --force-precompute
```

### Option B: Running Step-by-Step (Manual Commands)
To run each stage of the pipeline manually and observe intermediate output:

```bash
# 1. Run precomputation (one-time, ~2 min on 100K candidates)
python scripts/precompute.py --candidates ./candidates.jsonl --base-dir .

# 2. Run ranking (produces submission.csv in ~5.2 seconds)
python src/rank.py --candidates ./candidates.jsonl --out ./submission.csv

# 3. Validate format before submitting
python scripts/validate_submission.py --submission ./submission.csv
```

---

## Validation

To verify the ranking logic, suppression rules, and diversity constraints, you can execute our validation suite.

### Option A: Running the Full Validation Suite (Single-Command Shortcut)
To run the full sequential validation suite offline against the current state of `submission.csv` and the pipeline:

```bash
python scripts/run_full_validation.py
```

This script will run the following checks in order:
1. **Honeypot Injection Test:** Clones a top-ranked candidate and injects all 7 synthetic violation types from `validate_pipeline.py` into a temporary pool, confirming zero honeypot leakage into the top-100 output.
2. **Diversity Audit:** Asserts signature and employer concentration constraints from `validate_pipeline.py` against the current `submission.csv`.
3. **c5 Boundary-Gap Test:** Validates that the `c5` engagement mismatch check fires correctly under the Option B threshold (connections=1, appearances=0, endorsements=0).
4. **Probe-set NDCG Check:** Computes `NDCG@10` against hand-labeled probe set reference points (reports `None` if IDs are not present in the Stage 1 pool, which is expected on the full pool).

At completion, it prints a single pass/fail summary table and exits zero only if all tests pass.

### Option B: Running Manual Diagnostics
You can also run specific diagnostic scripts individually:
```bash
# 1. Run live feature profile latency check
python diagnostics/diag_profile_live_features.py

# 2. Verify c5 boundary condition checks
python diagnostics/verify_c5_thresholds.py
```

---

## Architecture Summary

| Stage | Module | Operation | Runtime |
|-------|--------|-----------|---------|
| **Offline** | `scripts/precompute.py` | BM25 indexing, static features calculation, training | ~7 min |
| **0** | `src/rank.py` | Load precomputed artifacts (BM25, LightGBM, static features) | 1.41s |
| **1** | `src/retrieval.py` | Dual-Pass BM25 Retrieval (top 5,000 + rare-term pool) | 0.05s |
| **2** | `src/rank.py` | Load records for retrieved candidates via offset index | 0.54s |
| **2b** | `src/features.py` | Feature extraction (live features + static features lookup) | 0.55s |
| **4** | `src/rank.py` | LightGBM LambdaRank inference | 0.01s |
| **5** | `src/reasoning.py` | Deterministic reasoning compiler | 2.51s |
| **6** | `src/rank.py` | Monotonicity, honeypot, diversity audits + CSV write | <0.01s |
| **Total** | | **End-to-end** | **5.10s** |

### Key Design Decisions

**Non-Circular Weak Supervision (Section 6):**
Training labels are computed as `hard_req_coverage × consistency_score`, explicitly excluding `bm25_score`. The model then learns to combine `bm25_score` with 21 other features to predict these labels — discovering organic interactions rather than memorizing a heuristic.

**22-Feature Matrix (Section 4.2):**
Every feature maps to a specific field in `candidate_schema.json`. No invented fields, no hallucinated values. Includes 5 adversarial detection functions (domain mismatch, template detection, production signal log, LangChain dabbler, CV/speech specialist).

**5 Consistency Checks (Section 5):**
`consistency_score = c1 × c2 × c3 × c4 × c5`
A single logical inconsistency zeros out the composite score. Checks: timeline impossibility, signup anomaly, salary inversion, assessment contradiction, engagement mismatch.

**Deterministic Output:**
All dates relative to `REFERENCE_DATE = date(2026, 1, 1)` constant — never `datetime.now()`. Tiebreaking by ascending `candidate_id`. Docker output is byte-identical regardless of run date.

**Blocking Audits Before CSV Write:**
- Honeypot audit: `assert count(consistency_score < 0.25) < 10`
- Diversity audit (from `validate_pipeline.check_top100_diversity`): blocks if any company > 30% or any archetype signature > 25%
- If either fails: `sys.exit` with non-zero code — no silent failure

---

## File Structure

```
├── data/
│   └── skill_aliases.json          # JD taxonomy (authoritative, do not modify)
├── precomputed/                     # Generated by precompute.py / rebuild_fast_artifacts.py
│   ├── vocab.pkl                   # BM25 Vocabulary term -> column index (19.5 KB)
│   ├── bm25_matrix.npz             # Vectorized Scipy BM25 CSR matrix (39.6 MB)
│   ├── candidate_offsets.pkl       # Candidate binary byte-offset index (2.0 MB)
│   ├── lgbm_model.txt              # Trained LightGBM booster in native text (1.3 MB)
│   ├── static_features.pkl         # Precomputed 18 static features dictionary (21.7 MB)
│   ├── bm25_index.pkl              # Legacy BM25Okapi index fallback (146.2 MB)
│   ├── candidate_ids.pkl           # Legacy candidate IDs fallback (1.5 MB)
│   ├── weak_labels.pkl             # Legacy training labels fallback (2.4 MB)
│   └── lgbm_model.pkl              # Legacy LightGBM pickle fallback (1.4 MB)
├── logs/                            # Runtime logs (generated by rank.py)
├── src/
│   ├── __init__.py                 # src package marker
│   ├── jd_parser.py                # JD requirement extraction
│   ├── retrieval.py                # Dual-pass BM25 retrieval
│   ├── features.py                 # 22-feature matrix + adversarial functions
│   ├── reasoning.py                # Deterministic reasoning compiler
│   └── rank.py                     # Main entry point
├── scripts/
│   ├── precompute.py               # Offline: BM25 + LightGBM training
│   ├── app.py                      # Streamlit sandbox (lite mode, ≤1GB RAM)
│   ├── validate_submission.py      # Format validator
│   ├── validate_pipeline.py        # Provided validation module (imported, not modified)
│   └── rebuild_fast_artifacts.py   # Utility to build fast artifacts
├── requirements.txt                # All deps pinned
├── Dockerfile                      # CPU-only, --network none compatible
├── docker-entrypoint.sh            # Pipeline mode selector
├── submission_metadata.yaml        # Competition metadata
└── README.md                       # This file
```

---

## Streamlit App Deployment (Free Tier)

The `scripts/app.py` Streamlit sandbox runs in **lite mode** (max 10,000 candidates, ≤1 GB RAM).

### Local
```bash
streamlit run scripts/app.py
```

### Streamlit Cloud (Free Tier)
1. Push this repo to GitHub (public, or connected private).
2. Navigate to [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Select: Repo → Branch (`main`) → Main file (`scripts/app.py`).
4. Click **Deploy**. Streamlit Cloud reads `requirements.txt` automatically.
5. The app URL is `https://<your-slug>.streamlit.app`.

> **Important:** The `precomputed/` artifacts (BM25 index fallback: 146 MB) must be committed to the repo OR hosted externally (e.g., Hugging Face Hub). The full `candidates.jsonl` is not needed — the app accepts uploads.

---

## Runtime Constraints (All Enforced)

| Constraint | Value | Enforcement |
|-----------|-------|-------------|
| Wall-clock | ≤5 min | Assertion + sys.exit(4) if exceeded |
| RAM | ≤16 GB | BM25 retrieval limits to top-5000 candidates |
| Network | Zero | `--network none` in Docker; no imports make network calls |
| Disk | ≤5 GB | Total artifacts: ~208 MB |
| Output rows | Exactly 100 | `assert len(df) == 100` before CSV write |
| Monotonicity | Non-increasing | `assert_monotonicity()` before CSV write |
| Tiebreaking | Ascending candidate_id | `sorted(..., key=lambda x: (-x[1], x[0]))` |

---

## AI Tool Disclosure

This submission was developed with the assistance of **Google DeepMind's Antigravity AI coding assistant** (using the Gemini 3.5 model).

Specifically, the system was developed through a highly iterative, diagnose-first programming process:
- **Code Scaffolding & Reorganization:** Partitioned the loose roots into structured `src/` and `scripts/` modules, implementing robust path-bootstrapping to resolve cross-directory imports dynamically.
- **Latency Diagnostics & Optimizations:** Diagnosed a 13.5x latency regression to a broken charset check in `SequenceMatcher`. Designed a candidate byte-offset binary index to bypass JSONL parsing (Stage 2: 4s -> 0.5s), vectorized Scipy BM25 matrix calculations (Stage 0: 20s -> 1.2s), and offloaded 18 JD-independent features to offline precomputation (Stage 2b features: 12.91s -> 0.55s), achieving a total end-to-end pipeline run speed of **5.10s** (a 15.4x improvement over the initial run).
- **Logical Consistency Auditing:** SWE-diagnosed and sweeper-tested the boundary gap in the `c5` engagement mismatch check across the entire 100K candidate pool. Ran a 7-threshold parameter sweep to safely establish the Option B (60/15/4) boundary to suppress the verified honeypot trap candidate `CAND_0019184` with zero false-positives on real candidates.
- **Reasoning Variety & Tone Scaling:** Implemented a deterministic MD5-based variety engine to rotate 4 different reasoning templates across consecutive ranks, while enforcing priority checklists for concerns.

All architectural designs, scoring weights, threshold specifications, and diagnostic approvals were directed and verified by the human team members at every stage of development.

---

## Troubleshooting

**`precompute.py` fails with memory error:**
Reduce the indexing batch size or run on a machine with ≥16 GB RAM.

**`rank.py` fails diversity audit:**
The top-100 candidates are too homogeneous. This indicates a feature weight imbalance. Check LightGBM feature importances and consider adjusting the training label distribution.

**Docker build fails on arm64 Mac:**
LightGBM wheels are available for arm64. Use `--platform linux/amd64` if cross-building for a cloud runner.
