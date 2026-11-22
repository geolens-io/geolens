# ADR-010: The manifest owns a map's keyed layers

**Status:** accepted. **Scope:** what a republish of a publish manifest does
to the layers of a map that people have also edited in GeoLens.

## Context

A publish manifest (version 2) can create a map and update it again on every
publish from a desktop GIS project. Between publishes, people open the same
map in the map builder: they restyle layers, hide or remove them, and add
layers of their own. The manifest's `styling` setting decides whether a
republish overwrites the styling of the layers it publishes: `replace`
always does, `keep` never does, and `replace_if_unedited`, the default, does
unless someone edited that styling in GeoLens since the last publish that
replaced it.

That setting answers how the published layers look. It leaves open which
layers the map has and what data each one shows, when the project and the
web map disagree.

## Decision

The manifest decides which keyed layers a map has and which dataset each
keyed layer shows. The `styling` setting decides only how they look. Layers
added in the builder carry no key, and a publish leaves their place and
styling alone.

- A keyed layer the manifest no longer lists is removed and reported as
  `A059`, even when a `replace_if_unedited` publish keeps the map's styling
  because someone restyled it. Only `keep` leaves such a layer in place, and
  so does a publish by someone who can't read the layer's dataset.
- A keyed layer someone removed in the builder comes back on the next
  publish, because nothing records the removal. To keep a published layer
  off the web map, hide it: a hidden layer is a styling edit, and a
  `replace_if_unedited` publish keeps it hidden.
- When styling is kept and the manifest points a layer's key at another
  dataset, the layer moves to that dataset and keeps its styling if the
  styling still works there: the geometry type matches, and every column its
  styling, labels, popup, filter and dashboard widgets read exists with a
  type that supports how it is used (a graduated colour or a histogram needs
  a number). Otherwise that layer alone takes the manifest's styling, with a
  warning that names what didn't fit. Until this lands, the layer stays on
  its earlier dataset and the publish answers warning `A073`.

We considered recording a builder removal so that later publishes leave the
layer out until the project drops it and adds it again. It adds state every
publishing app would have to explain, and a layer would then be missing from
the web map while still present in the project. We also considered freezing
the layer list whenever styling is kept. That would leave a web map showing
data the project stopped publishing, with no sign of it in the publish
result.

## Consequences

The project is the source of truth for the keyed layers: what the project
publishes is on the map, and a keyed layer the project dropped is gone,
except under `keep` or when the publisher can't read its dataset. Layers
added in the builder stay. A builder edit survives a republish as styling,
never as a change to the keyed layer list. The publish result names every
layer it removed (`A059`), so a publishing app can tell its user what a
republish took off the map.

Someone who removes a published layer in the builder sees it return on the
next publish. Hiding it is the supported way to keep it off the map: the
layer stays hidden while styling is kept, under `keep` or under
`replace_if_unedited` once the edit is recorded, and a `replace` publish
shows it again.
