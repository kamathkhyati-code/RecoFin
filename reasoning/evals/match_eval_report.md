# Matching Eval + Ablation Report (B15)

Golden dataset: 9 book txns, 9 source txns, 8 true matches, 1 book-only and 1 source-only leftovers.

| Layer | Matched | Precision | Recall | Auto-match rate | Hallucination rate |
|---|---|---|---|---|---|
| det_only | 6 | 1.0 | 0.75 | 0.6667 | 0.0 |
| det_plus_llm | 8 | 1.0 | 1.0 | 0.5 | 0.0 |
| det_plus_llm_plus_rag | 8 | 1.0 | 1.0 | 0.625 | 0.0 |

Reading the table: deterministic-only misses the two semantic-only pairs (SM1/SM2), so recall is below 1.0. Adding the LLM layer recovers both, taking recall to 1.0 with no precision loss. Adding match memory (RAG) does not change which pairs are matched -- it only recalibrates confidence for the pair with prior history (B-SM1/S-SM1, pre-seeded here), raising the auto-match rate without touching precision or recall.