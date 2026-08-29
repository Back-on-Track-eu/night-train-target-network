"""osm_survey — read OSM and work out what the catalogue should say.

Runs entirely separately from `osm_pipe`. Nothing in the build pipeline imports
this package, and nothing here writes a file the pipeline reads: it prints YAML
fragments for a human to review and paste. Every one of them is a claim about
the world — which ways belong to a project, which two track ends are the same
junction — and those belong in a diff someone read.
"""

__version__ = "0.1.0"
