import { cn } from "../../lib/utils";
import { forwardRef, type ButtonHTMLAttributes } from "react";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "outline";
  size?: "sm" | "md" | "lg";
  isLoading?: boolean;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", isLoading, children, disabled, ...props }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={cn(
          "inline-flex items-center justify-center gap-2 font-medium transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed",
          {
            // Primary - Sage green solid button
            "bg-primary text-white hover:bg-primary-dark rounded-full shadow-sm": variant === "primary",
            // Secondary - Muted background
            "bg-surface-muted text-foreground hover:bg-border rounded-xl": variant === "secondary",
            // Ghost - Transparent
            "bg-transparent text-foreground-muted hover:bg-surface-muted hover:text-foreground rounded-xl": variant === "ghost",
            // Outline - Border only
            "border border-border bg-surface text-foreground hover:bg-surface-muted rounded-full": variant === "outline",
            // Sizes
            "px-4 py-2 text-sm": size === "sm",
            "px-6 py-3 text-sm": size === "md",
            "px-8 py-4 text-base": size === "lg",
          },
          className
        )}
        {...props}
      >
        {isLoading && (
          <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
        )}
        {children}
      </button>
    );
  }
);

Button.displayName = "Button";

export { Button };
