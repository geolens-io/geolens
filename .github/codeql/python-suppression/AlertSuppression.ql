/**
 * @name Alert suppression
 * @description Generates information about alert suppressions.
 * @kind alert-suppression
 * @id py/geolens-alert-suppression
 */

// Derived from github/codeql `python/ql/src/AlertSuppression.ql`, with the
// NoqaSuppressionComment class deliberately left out. That is the whole
// reason this query is vendored instead of referenced as
// `codeql/python-queries:AlertSuppression.ql`.
//
// Upstream maps every `# noqa` comment to a BARE `lgtm` annotation covering
// the entire line, and a bare annotation suppresses EVERY rule on that line
// rather than one named rule. `backend/` carries 332 `# noqa` comments,
// written to silence ruff, by people who were not deciding anything about
// code scanning. Honouring them here would turn each of those lines into a
// standing auto-dismissal zone for any alert that ever lands on it --
// silently, and most dangerously at the raw-SQL sites where a `# noqa: S608`
// already sits (`app/processing/analysis/tasks.py`).
//
// With that class dropped, the only thing that can suppress an alert is an
// explicit `# codeql[<rule-id>]` comment on its own line directly above the
// alert, naming the rule it suppresses. That is a reviewable, greppable,
// per-rule decision, which is what AGENTS.md > Standing CodeQL policy
// intended to adopt.
//
// The `lgtm[<rule-id>]` form also still works: it comes from the shared
// upstream module below, not from anything added here. No such comment
// exists in this repository.
//
// Keep this query in sync with upstream when the CodeQL bundle moves, and
// keep the omission. `backend/tests/test_codeql_qtable_suppressions.py`
// fails if the excluded class comes back.

private import codeql.util.suppression.AlertSuppression as AS
private import semmle.python.Comment as P

class AstNode instanceof P::AstNode {
  predicate hasLocationInfo(
    string filepath, int startline, int startcolumn, int endline, int endcolumn
  ) {
    super.getLocation().hasLocationInfo(filepath, startline, startcolumn, endline, endcolumn)
  }

  string toString() { result = super.toString() }
}

class SingleLineComment instanceof P::Comment {
  predicate hasLocationInfo(
    string filepath, int startline, int startcolumn, int endline, int endcolumn
  ) {
    super.getLocation().hasLocationInfo(filepath, startline, startcolumn, endline, endcolumn)
  }

  string getText() { result = super.getContents() }

  string toString() { result = super.toString() }
}

import AS::Make<AstNode, SingleLineComment>
