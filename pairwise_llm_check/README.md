# experiments/pairwise_llm_check/

## What This Experiment Does

This is an **offline experiment** that generates better LightGBM training labels
by replacing the heuristic weak_label = hard_req_coverage × consistency_score × jd_penalty
with LLM pairwise judgments on sampled Stage 1 candidates.

### Pipeline Summary

1. Load Stage 1 BM25 retrieval pool.
2. Stratified sample of candidates weighted toward the current model's top and boundary regions.
3. Generate pairwise matchups; annotate with quantized LLaMA via Ollama.
4. Convert pairwise verdicts → Elo ratings → 0–3 integer relevance labels.
5. Retrain LightGBM on these labels using identical hyperparameters to precompute.py.
6. Save the new model as precomputed/lgbm_model_llm.pkl.
7. Print a comparison report: top-10 overlap, Spearman correlation, honeypot audit.
