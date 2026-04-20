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
      <div
        className={cn(
          "border-3 border-border border-t-primary rounded-full animate-spin",
          {
            "w-5 h-5 border-2": size === "sm",
            "w-8 h-8 border-3": size === "md",
            "w-12 h-12 border-4": size === "lg",
          }
        )}
      />
      {message && (
        <p className="mt-4 text-foreground-muted text-sm font-medium">{message}</p>
      )}
      {submessage && (
        <p className="mt-1 text-foreground-subtle text-xs">{submessage}</p>
      )}
    </div>
  );
}

export { Spinner };
