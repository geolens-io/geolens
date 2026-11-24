# ADR-009: Manifest keys are unique across the server

**Status:** accepted. **Scope:** how a publish manifest names the datasets,
maps and map layers it creates, and who may reuse a name.

## Context

A publish manifest gives each item a manifest key, a stable name the
publishing app stores in its project. Applying the manifest again finds the
item by its key and updates it instead of making another. Dataset keys have
always been unique across the server: a key on a dataset the caller can't
write is refused, whoever else owns it.

Manifest version 2 adds maps, so maps and the layers inside them need keys
too. A map keeps its key in `maps.manifest_key` and a layer in
`map_layers.manifest_key`.

## Decision

A map's manifest key is unique across the server, like a dataset's. A map
layer's key is unique within its map, so two maps may each have a layer
called `parks`. Partial unique indexes enforce both, and layers added in the
map builder carry no key.

- A key on a map the caller can't edit answers `A050`. The answer says only
  that the key is taken; it never names the map, its owner or its id.
- Duplicating a map clears the keys on the copy and on its layers. The copy
  is a new map that no manifest has published.
- Transferring a map to another owner keeps its keys. The new owner's
  republish updates the map, and the previous owner's gets `A050`.

We considered keys unique per owner, so that two people could publish the
same project and each get their own map. That doesn't work while dataset
keys are global: a copied project is refused on its datasets before its map
is reached. Per-owner map keys would also make an ownership transfer collide
whenever the new owner already had a map under the same key. With one rule,
a publishing app explains a refused key the same way for a dataset and a map.

## Consequences

A key someone else published answers `A050`, and the publishing app's fix is
to publish as new with a key it generates. Apps generate keys from a random
UUID, so two people only share a key when one copied the other's project.

An admin signed in, or using a full key, can update any keyed map, as with
datasets. A publish key acts only on its owner's own maps, so an admin's
publish key gets `A050` on anyone else's.

Since a key outlives a transfer, whoever owns the map now controls what the
next publish under that key does to it.
