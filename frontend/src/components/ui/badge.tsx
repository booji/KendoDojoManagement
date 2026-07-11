import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "group/badge inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-4xl border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
        secondary:
          "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
        destructive:
          "bg-destructive/10 text-destructive focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:focus-visible:ring-destructive/40 [a]:hover:bg-destructive/20",
        outline:
          "border-border text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground",
        ghost:
          "hover:bg-muted hover:text-muted-foreground dark:hover:bg-muted/50",
        link: "text-primary underline-offset-4 hover:underline",
        success:
          "bg-success/10 text-success focus-visible:ring-success/20 dark:bg-success/20 dark:focus-visible:ring-success/40 [a]:hover:bg-success/20",
        warning:
          "bg-warning/10 text-warning focus-visible:ring-warning/20 dark:bg-warning/20 dark:focus-visible:ring-warning/40 [a]:hover:bg-warning/20",
        info: "bg-info/10 text-info focus-visible:ring-info/20 dark:bg-info/20 dark:focus-visible:ring-info/40 [a]:hover:bg-info/20",
        category: "border-transparent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

/** Number of distinguishable palette slots the `category` variant cycles
 * through (backed by `--category-1..8` in index.css). */
const CATEGORY_SLOT_COUNT = 8

const normalizeCategory = (category: number | string): number => {
  const index = typeof category === "number" ? category : Number(category)
  const safeIndex = Number.isFinite(index) ? Math.trunc(index) : 0
  return ((safeIndex % CATEGORY_SLOT_COUNT) + CATEGORY_SLOT_COUNT) % CATEGORY_SLOT_COUNT
}

interface BadgeCategoryProps {
  category?: number | string
}

function Badge({
  className,
  variant = "default",
  category,
  render,
  style,
  ...props
}: useRender.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> &
  BadgeCategoryProps) {
  const categoryIndex =
    variant === "category" && category !== undefined
      ? normalizeCategory(category)
      : undefined

  const categoryStyle =
    categoryIndex !== undefined
      ? {
          ...style,
          color: `var(--category-${categoryIndex + 1})`,
          backgroundColor: `color-mix(in oklch, var(--category-${categoryIndex + 1}) 15%, transparent)`,
        }
      : style

  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
        style: categoryStyle,
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
      ...(categoryIndex !== undefined ? { category: categoryIndex } : {}),
    },
    stateAttributesMapping: {
      // useRender's default state->data-attribute mapping treats `0` (and
      // other falsy values) as "absent", which would drop
      // data-category="0" for the first category slot. Map explicitly so
      // every non-undefined category index renders.
      category: (value) =>
        value === undefined ? null : { "data-category": String(value) },
    },
  })
}

export { Badge, badgeVariants }
