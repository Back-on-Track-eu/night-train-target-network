"""
model_docs
==========
Documentation generation for the calculation model, split into one
extraction layer and one renderer per output artefact:

  extract.py          registries, versions, the ref graph, standard values,
                      parameter tables, the cost/revenue tree — everything
                      read out of the model source of truth
  render_model_md.py  docs/MODEL.md, the developer reference
  render_site.py      docs-site/, the public documentation site

Both renderers read the same extraction layer, so the two artefacts can
differ in prose but never in facts. The CLI is
scripts/generate_model_docs.py.
"""
