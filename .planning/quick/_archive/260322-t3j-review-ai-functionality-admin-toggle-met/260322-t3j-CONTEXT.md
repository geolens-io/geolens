# Quick Task 260322-t3j: Review AI Functionality - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Task Boundary

Review AI functionality - admin toggle, metadata assist and map creation/chat. Identify any gaps, issues or concerns. Suggest enhancements as needed. Also, make a UI indicator that Map AI components are experimental.

</domain>

<decisions>
## Implementation Decisions

### Experimental Badge Style
- Subtle badge: small "Experimental" chip/badge next to the chat panel header and chat toggle button
- Amber/yellow coloring, rounded corners, matching existing badge styles
- NOT a warning banner or tooltip-only approach

### Review Scope
- Full audit covering both UX/functionality gaps AND code quality/security
- UX: missing features, broken flows, UX inconsistencies, edge cases
- Code: injection risks, error handling gaps, API key exposure, prompt injection vulnerabilities

### Enhancement Scope
- Fix gaps and issues found during review — implement code changes
- Implement the experimental badge
- Document larger enhancement suggestions as recommendations (not implemented)

### Claude's Discretion
- Prioritization of which fixes to implement vs document
- Specific wording of experimental badge text

</decisions>

<specifics>
## Specific Ideas

- Experimental badge on ChatPanel header and chat toggle button in MapBuilderPage
- Review all three AI areas: admin settings, metadata assist, map chat

</specifics>

<canonical_refs>
## Canonical References

No external specs — requirements fully captured in decisions above

</canonical_refs>
