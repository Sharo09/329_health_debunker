import { CheckCircle2, XCircle, HelpCircle, AlertTriangle } from "lucide-react";
import { Card, CardContent } from "../ui/Card";
import { cn } from "../../lib/utils";
import type { Verdict } from "../../api";

interface VerdictCardProps {
  verdict: Verdict;
}

const verdictConfig = {
  supported: {
    label: "Supported by Evidence",
    description: "The research literature supports this claim",
    icon: CheckCircle2,
    bg: "bg-supported-bg",
    border: "border-supported/30",
    iconBg: "bg-supported/20",
    iconColor: "text-supported",
    textColor: "text-foreground",
    bar: "bg-supported",
  },
  contradicted: {
    label: "Contradicted by Evidence",
    description: "The research literature contradicts this claim",
    icon: XCircle,
    bg: "bg-unsupported-bg",
    border: "border-unsupported/30",
    iconBg: "bg-unsupported/20",
    iconColor: "text-unsupported",
    textColor: "text-foreground",
    bar: "bg-unsupported",
  },
  insufficient_evidence: {
    label: "Insufficient Evidence",
    description: "Not enough research to draw a firm conclusion",
    icon: HelpCircle,
    bg: "bg-surface-muted",
    border: "border-border",
    iconBg: "bg-insufficient/10",
    iconColor: "text-insufficient",
    textColor: "text-foreground",
    bar: "bg-insufficient",
  },
};

function VerdictCard({ verdict }: VerdictCardProps) {
  const config = verdictConfig[verdict.verdict];
  const Icon = config.icon;
  const confidence = Math.round(verdict.confidence_percent);

  return (
    <Card className={cn("overflow-hidden rounded-2xl border-0", config.bg)}>
      <CardContent className="p-8">
        <div className="flex items-start gap-5">
          <div className={cn("flex-shrink-0 p-3 rounded-2xl", config.iconBg)}>
            <Icon className={cn("w-8 h-8", config.iconColor)} />
          </div>
          
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium tracking-widest text-foreground-muted uppercase mb-2">
              Verdict
            </div>
            <h3 className={cn("text-2xl font-serif mb-2", config.textColor)}>
              {config.label}
            </h3>
            <p className="text-sm text-foreground-muted mb-5">
              {config.description}
            </p>

            {/* Confidence Bar */}
            <div className="mb-5">
              <div className="flex justify-between text-xs mb-2">
                <span className="text-foreground-muted">Confidence Level</span>
                <span className="font-semibold text-foreground">{confidence}%</span>
              </div>
              <div className="h-2 bg-surface rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all duration-700 ease-out", config.bar)}
                  style={{ width: `${confidence}%` }}
                />
              </div>
            </div>

            {/* Reasoning */}
            {verdict.verdict_reasoning && (
              <p className="text-sm text-foreground-muted leading-relaxed">
                {verdict.verdict_reasoning}
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function DemographicCaveat({ text }: { text: string }) {
  return (
    <Card className="bg-mixed-bg border-0 rounded-2xl">
      <CardContent className="p-5 flex items-start gap-4">
        <div className="p-2 rounded-xl bg-mixed/20">
          <AlertTriangle className="w-5 h-5 text-mixed" />
        </div>
        <div>
          <div className="text-xs font-medium tracking-widest text-mixed uppercase mb-1">
            Demographic Note
          </div>
          <p className="text-sm text-foreground-muted">{text}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export { VerdictCard, DemographicCaveat };
