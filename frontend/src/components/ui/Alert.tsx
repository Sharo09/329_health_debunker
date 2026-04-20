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
        "flex items-start gap-3 p-4 rounded-lg text-sm",
        {
          "bg-blue-50 text-blue-800 border border-blue-200": variant === "info",
          "bg-mixed-bg text-amber-800 border border-amber-300": variant === "warning",
          "bg-unsupported-bg text-red-800 border border-red-300": variant === "error",
          "bg-supported-bg text-green-800 border border-green-300": variant === "success",
        },
        className
      )}
      {...props}
    >
      <Icon className="w-5 h-5 flex-shrink-0 mt-0.5" />
      <div className="flex-1">{children}</div>
    </div>
  );
}

export { Alert };
