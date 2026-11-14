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

## Atlas Vector Search

The final bank review can use Voyage embeddings and Atlas Vector Search. Set
`VOYAGE_API_KEY` in the ignored `backend/.env`. From `backend/`, seed the
corpus and build its indexes:

```bash
.venv/bin/python -m app.seed_reference_data --apply
.venv/bin/python -m app.setup_reference_search
.venv/bin/python -m app.setup_reference_search --query "When must a bank verify corporate beneficial ownership?"
```

Index creation requires Atlas Managed MCP permissions. Wait for the Atlas indexes
to become queryable before running the probe. The setup embeds passages with
Voyage `voyage-4-lite` at 256 dimensions and creates a cosine vector index on
each collection. Reruns reuse stored embeddings for the configured model and dimension.

Restart FastAPI after configuring the key. **Verify evidence and assess risk**
then retrieves ranked passages separately from the two indexes and uses the same
results for verification and risk assessment. Voyage receives the search query
based on case topics, sector and product. The intake chatbot continues to use
its intake skill. Without a Voyage key, final review uses the seeded corpus.
