import { cn } from "../../lib/utils";
import { AlertCircle, AlertTriangle, Info, CheckCircle2 } from "lucide-react";
import { type HTMLAttributes } from "react";

export interface AlertProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "info" | "warning" | "error" | "success";
}

const iconMap = {
  info: Info,
  warning: AlertTriangle,
  error: AlertCircle,
  success: CheckCircle2,
};

function Alert({ className, variant = "info", children, ...props }: AlertProps) {
  const Icon = iconMap[variant];
  
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 p-4 rounded-2xl text-sm",
        {
          "bg-primary/10 text-foreground border-0": variant === "info",
          "bg-mixed-bg text-foreground border-0": variant === "warning",
          "bg-unsupported-bg text-foreground border-0": variant === "error",
          "bg-supported-bg text-foreground border-0": variant === "success",
        },
        className
      )}
      {...props}
    >
      <Icon className={cn(
        "w-5 h-5 flex-shrink-0 mt-0.5",
        {
          "text-primary": variant === "info",
          "text-mixed": variant === "warning",
          "text-unsupported": variant === "error",
          "text-supported": variant === "success",
        }
      )} />
      <div className="flex-1">{children}</div>
    </div>
  );
}

export { Alert };
