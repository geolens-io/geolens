# GeoLens Governance

GeoLens is a founder-led, open-source project. This document describes how
decisions are made, who makes them, and what contributors can expect. It is
intentionally lightweight and honest about the project's current size — GeoLens
is maintained by a single person today, and the process is sized accordingly.

## Project leadership

GeoLens follows a **BDFL (Benevolent Dictator For Life)** model. [@ishiland](https://github.com/ishiland)
is the sole maintainer and the final decision-maker on the project's direction,
architecture, and releases. Copyright in the project is held by Carto Concepts,
LLC and the GeoLens contributors, who retain copyright in their contributions
under the project's [DCO](.github/CONTRIBUTING.md) (Apache-2.0 inbound=outbound);
the code is licensed under Apache-2.0 (see [LICENSE](LICENSE)).

See [MAINTAINERS.md](MAINTAINERS.md) for the current maintainer list and areas.

## Decision-making

Most decisions are made by **lazy consensus**: a proposal (an issue or pull
request) moves forward if no one with relevant context raises a blocking
objection within a reasonable window. When there is disagreement, the maintainer
makes the final call.

- Routine changes (bug fixes, docs, small features) are decided on the PR.
- Larger or breaking changes should start as a GitHub issue or a Discussion so
  the design can be agreed before code is written.

## Becoming a maintainer

There is no fixed timeline. A contributor may be invited to become a maintainer
after a sustained track record of high-quality merged PRs and constructive
participation. New maintainers are nominated by an existing maintainer and
confirmed by the current maintainers.

Maintainers may be moved to emeritus status after extended inactivity (roughly
six months) or by agreement among the maintainers. Emeritus maintainers are
welcome to return.

## Release authority

Only maintainers cut release tags and publish official builds. The release
process is documented in [RELEASE.md](RELEASE.md); published images and packages
always originate from a maintainer-cut `v*.*.*` tag, never from a contributor
branch.

## Deprecation policy

GeoLens aims to avoid gratuitous breaking changes. When a breaking change is
necessary, it is called out in [CHANGELOG.md](CHANGELOG.md), and — where
feasible — announced at least one minor release ahead of the change so operators
have time to adapt.

## Roadmap and priorities

Priorities are tracked openly through GitHub issues and milestones. Feature ideas
and larger proposals are best raised in GitHub Discussions before they become
issues. The roadmap is best-effort and reflects the maintainer's available time.

## Response expectations

GeoLens is maintained on a **best-effort** basis. There is no service-level
guarantee on issue or pull-request response times. Security reports are the
exception: they are acknowledged within 48 hours per the
[Security Policy](.github/SECURITY.md).
