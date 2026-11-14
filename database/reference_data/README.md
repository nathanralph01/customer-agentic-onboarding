# Canadian business onboarding reference data

This corpus covers selected Canadian federal requirements and fictional bank
procedures for a corporate business account. The public records are paraphrases
with section-level citations and official source links checked on November 14,
2026. Check the current official text and applicability before relying on a
summary for a real decision.

| File | Contents | Destination |
| --- | --- | --- |
| `regulations.json` | PCMLTFA, PCMLTFR, PIPEDA, FINTRAC guidance and OSFI guidelines | `regulations` |
| `procedures.json` | Demo bank evidence, scoring, escalation, document release and privacy procedures | `procedures` |
| `retrieval_cases.json` | Knowledge questions, expected citations and answer criteria | Local evaluation fixtures |

From `backend/`, using the backend virtual environment and existing Atlas
Managed MCP settings:

```bash
.venv/bin/python -m app.seed_reference_data
.venv/bin/python -m app.seed_reference_data --apply
```

The first command validates the files locally. The second writes only the two
reference collections. Reruns reuse the same versioned IDs and preserve extra
fields such as embeddings. Publish a new record version when source or policy
content changes.

Use `text` as the passage text and keep `_id`, `title`, `citation`,
`source_url`, `kind` and `version` with each retrieval result. Use the product,
jurisdiction and topic fields when filtering. Cite official sources for legal
claims and the demo policy ID and version for bank routing. Keep evaluation cases
outside the retrieval index so answers cannot be retrieved from the fixtures.

This seed step prepares the corpus for retrieval. The current intake chatbot
still uses its intake skill and does not query these collections. Embeddings,
search indexes and agent retrieval wiring are separate integration steps.
