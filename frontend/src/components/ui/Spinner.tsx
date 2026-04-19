import { cn } from "../../lib/utils";

interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
  message?: string;
  submessage?: string;
}

function Spinner({ size = "md", className, message, submessage }: SpinnerProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-10", className)}>
      <div className="relative">
        {/* Outer glow */}
        <div className="absolute inset-0 bg-primary/10 rounded-full blur-md animate-pulse" />
        
        {/* Spinner */}
        <div
          className={cn(
            "relative border-2 border-surface-muted border-t-primary rounded-full animate-spin",
            {
              "w-5 h-5": size === "sm",
              "w-8 h-8": size === "md",
              "w-12 h-12": size === "lg",
            }
          )}
        />
      </div>
      {message && (
        <p className="mt-4 text-foreground font-medium text-sm">{message}</p>
      )}
      {submessage && (
        <p className="mt-1 text-foreground-subtle text-xs">{submessage}</p>
      )}
    </div>
  );
}

export { Spinner };
