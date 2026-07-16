# Showcase

These files are illustrative excerpts kept for code-quality review — they
are not the product. They exist to demonstrate engineering and UX patterns
in isolation, safely, with no dependency on the private implementation:

| File | What it shows |
|------|----------------|
| `ui_pattern_demo.py` | A real, standalone excerpt of the dashboard's help-icon/section-header component, runnable with `streamlit run showcase/ui_pattern_demo.py` |
| `demo_policy_example.py` | A trimmed version of the production Demo Policy module — mode-gated behavior as a small, explicit set of functions |
| `acquisition_adapter_example.py` | A simplified illustration of the fetch → normalize → yield pattern used across the real (unpublished) acquisition adapters, against a bundled fixture instead of a live endpoint |

See [docs/ABOUT_THIS_REPO.md](../docs/ABOUT_THIS_REPO.md) for why the rest of the implementation is not here.
