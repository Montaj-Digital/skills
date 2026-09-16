# AI second brain instructions

This folder is a small AI second brain. It exists so useful context survives a single chat.

## Rules

- Treat `raw/` as source material. Read it, cite it and preserve it. Don't edit original sources.
- Treat `wiki/` as reviewed working knowledge. Update it when the human confirms a change.
- Read `index.md` first before answering questions against this brain.
- Cite source files for non-obvious factual claims.
- Mark unknowns clearly instead of guessing.
- Preserve contradictions and superseded decisions with dates and sources.
- Update `log.md` whenever you ingest a source, answer a useful query or record a decision.

## Core operations

### Ingest

Read a source, summarise it under `wiki/sources/`, then update the relevant reviewed pages.

### Query

Use `index.md` to choose the right context, answer with citations and list remaining unknowns.

### Update

When the human approves a decision, update `wiki/decisions.md`, any affected brief and `log.md`.

## Privacy

Don't ask for passwords, API keys, payment details or sensitive records. If a source is restricted, record where it lives and who controls it without copying the restricted content.
