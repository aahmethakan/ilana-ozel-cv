# PDF Parser v1

## Scope

- Parses machine-readable, text-based PDF files deterministically.
- Produces canonical document blocks with stable page and block references.
- Applies conservative section detection for standard headings and private-use bullet markers.
- Uses a simple general-purpose heuristic for multi-column text ordering.

## Known limitations

- Does not perform OCR for scanned PDFs.
- Does not repair malformed Unicode text.
- Does not infer geographic context, parallel memberships, or marker-to-label relationships.
- Does not classify headers, footers, images, logos, or other visual-only content.

## Future candidates

- Add confidence reporting with high, medium, and low classifications.
- Add optional geometry-aware and relationship-aware extraction where it can remain deterministic.
