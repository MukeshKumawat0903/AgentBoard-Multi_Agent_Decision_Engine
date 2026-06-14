/**
 * Card – shared raised-surface container.
 *
 * One place for the card recipe: rounded corners, raised surface token,
 * hairline ring instead of a hard border, soft layered shadow.
 */

import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Apply default inner padding (p-5). Disable for custom layouts. */
  padded?: boolean;
  /** Lift the card slightly on hover (for clickable cards). */
  interactive?: boolean;
  children: ReactNode;
}

export default function Card({
  padded = true,
  interactive = false,
  className = "",
  children,
  ...rest
}: CardProps) {
  return (
    <div
      className={`rounded-2xl bg-surface-raised ring-1 ring-black/5 dark:ring-white/10 shadow-card
                  ${interactive ? "transition-all duration-200 hover:-translate-y-0.5 hover:shadow-card-hover" : ""}
                  ${padded ? "p-5" : ""} ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}
