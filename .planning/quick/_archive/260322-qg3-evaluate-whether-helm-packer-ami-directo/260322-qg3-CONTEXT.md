# Quick Task 260322-qg3: Evaluate whether helm/, packer/, ami/ directories should move to separate repos - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Task Boundary

Evaluate whether helm/, packer/ directories (and packer/aws AMI template) should move to separate repos under the geolens-io GitHub organization. Produce a recommendation document with analysis.

Note: `ami/` directory does not exist. `packer/aws/geolens-ami.pkr.hcl` is the AMI artifact.

</domain>

<decisions>
## Implementation Decisions

### Scope of evaluation
- Recommendation document only — no repo changes or implementation
- Written analysis with pros/cons and clear recommendation

### CI/CD coupling
- Claude's discretion — investigate current CI state from repo to determine coupling level

### Versioning strategy
- Independent versioning recommended — helm chart and packer images version on their own cadence, referencing app image tags

</decisions>

<specifics>
## Specific Ideas

- Consider other items beyond helm/packer that may warrant separate repos (e.g., Terraform, docs, shared libraries)
- Evaluate GitHub organization structure best practices
- Consider monorepo vs polyrepo trade-offs specific to this project's scale

</specifics>

<canonical_refs>
## Canonical References

No external specs — requirements fully captured in decisions above

</canonical_refs>
