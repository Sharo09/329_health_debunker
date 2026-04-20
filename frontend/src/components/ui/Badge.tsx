import { cn } from "../../lib/utils";
import { type HTMLAttributes } from "react";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "supported" | "mixed" | "unsupported" | "insufficient" | "outline";
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
        {
          "bg-muted text-foreground-muted": variant === "default",
          "bg-supported-bg text-supported": variant === "supported",
          "bg-mixed-bg text-mixed": variant === "mixed",
          "bg-unsupported-bg text-unsupported": variant === "unsupported",
          "bg-insufficient-bg text-insufficient": variant === "insufficient",
          "border border-border bg-transparent text-foreground-muted": variant === "outline",
        },
        className
      )}
      {...props}
    />
  );
}

export { Badge };
