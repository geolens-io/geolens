// fix(#438): ARC-10 — was the scoped `@radix-ui/react-collapsible`; the app
// already depends on the umbrella `radix-ui` package for its other 20 primitives.
import { Collapsible as CollapsiblePrimitive } from "radix-ui"

const Collapsible = CollapsiblePrimitive.Root

const CollapsibleTrigger = CollapsiblePrimitive.CollapsibleTrigger

const CollapsibleContent = CollapsiblePrimitive.CollapsibleContent

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
