# Presentation

The capstone presentation is available in two formats:

- [`output/Sephora_Analytics_Pipeline.pptx`](output/Sephora_Analytics_Pipeline.pptx)
  — editable PowerPoint with speaker notes embedded on every slide.
- [`output/Sephora_Analytics_Pipeline.pdf`](output/Sephora_Analytics_Pipeline.pdf)
  — portable export for submission or backup.

[`speaker_notes.md`](speaker_notes.md) is the readable eight-minute script.
Its slide timings total exactly **8:00**.

## Rebuilding the deck

Microsoft PowerPoint is required because the build script uses the local Office
automation interface to create the editable file and PDF with matching layout.

```powershell
.\presentation\build_deck.ps1
```

The script reads the four verified PNGs in `docs/screenshots/`, creates both
deliverables under `presentation/output/`, and exports slide renders to
`tmp/presentation-render/` for visual QA. The render directory is intentionally
ignored; the PowerPoint, PDF, source script, and speaker notes are committed.

## Slide sequence

1. Project outcome and verified scale
2. Source data and cleaning rules
3. End-to-end architecture
4. Star schema and the reviewer-profile design decision
5. ETL quality, reconciliation, and incremental modes
6. Historical and incremental Airflow evidence
7. Streamlit dashboard and headline insights
8. Verified final state and live-demo route
