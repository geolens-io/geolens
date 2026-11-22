"use client"

import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { ToggleGroup as ToggleGroupPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

const toggleGroupVariants = cva(
  "group/toggle-group inline-flex items-center rounded-lg border bg-muted/40 p-1",
  {
    variants: {
      variant: {
        default: "border-border",
        outline: "bg-transparent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

const toggleGroupItemVariants = cva(
  "inline-flex items-center justify-center rounded-md border border-transparent font-medium whitespace-nowrap transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out outline-none forced-colors:focus-visible:outline-2 forced-colors:focus-visible:outline-solid forced-colors:focus-visible:-outline-offset-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "text-muted-foreground data-[state=on]:border-border data-[state=on]:bg-background data-[state=on]:text-foreground data-[state=on]:shadow-sm forced-colors:data-[state=on]:bg-[Highlight] forced-colors:data-[state=on]:text-[HighlightText] forced-colors:data-[state=on]:forced-color-adjust-none forced-colors:data-[state=on]:**:text-[HighlightText]",
        outline:
          "text-foreground/80 data-[state=on]:border-border data-[state=on]:bg-accent data-[state=on]:text-foreground forced-colors:data-[state=on]:bg-[Highlight] forced-colors:data-[state=on]:text-[HighlightText] forced-colors:data-[state=on]:forced-color-adjust-none forced-colors:data-[state=on]:**:text-[HighlightText]",
      },
      size: {
        default: "h-8 px-3 text-sm pointer-coarse:min-h-11",
        sm: "h-7 px-2.5 text-xs pointer-coarse:min-h-11",
        lg: "h-9 px-4 text-sm pointer-coarse:min-h-11",
        icon: "h-8 px-3 text-sm pointer-coarse:min-h-11 pointer-coarse:min-w-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function ToggleGroup({
  className,
  variant = "default",
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Root> &
  VariantProps<typeof toggleGroupVariants>) {
  return (
    <ToggleGroupPrimitive.Root
      data-slot="toggle-group"
      data-variant={variant}
      className={cn(toggleGroupVariants({ variant }), className)}
      {...props}
    />
  )
}

function ToggleGroupItem({
  className,
  variant = "default",
  size = "default",
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Item> &
  VariantProps<typeof toggleGroupItemVariants>) {
  return (
    <ToggleGroupPrimitive.Item
      data-slot="toggle-group-item"
      data-variant={variant}
      data-size={size}
      className={cn(toggleGroupItemVariants({ variant, size }), className)}
      {...props}
    />
  )
}

export { ToggleGroup, ToggleGroupItem, toggleGroupVariants, toggleGroupItemVariants }
