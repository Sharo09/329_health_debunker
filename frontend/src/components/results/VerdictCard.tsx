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
    text: "text-green-800",
    bar: "bg-supported",
    ringColor: "var(--color-supported)",
  },
  contradicted: {
    label: "Contradicted by Evidence",
    description: "The research literature contradicts this claim",
    icon: XCircle,
    bg: "bg-unsupported-bg",
    border: "border-unsupported/30",
    text: "text-red-800",
    bar: "bg-unsupported",
    ringColor: "var(--color-unsupported)",
  },
  insufficient_evidence: {
    label: "Insufficient Evidence",
    description: "Not enough research to draw a firm conclusion",
    icon: HelpCircle,
    bg: "bg-insufficient-bg",
    border: "border-insufficient/30",
    text: "text-gray-700",
    bar: "bg-insufficient",
    ringColor: "var(--color-insufficient)",
  },
};

function VerdictCard({ verdict }: VerdictCardProps) {
  const config = verdictConfig[verdict.verdict];
  const Icon = config.icon;
  const confidence = Math.round(verdict.confidence_percent);
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (Math.max(0, Math.min(100, confidence)) / 100) * circumference;

  return (
    <Card className={cn("overflow-hidden", config.bg, config.border)}>
      <CardContent className="p-6">
        <div className="flex flex-col sm:flex-row items-start gap-5">
          <div className={cn("flex-shrink-0 p-2 rounded-xl", config.bg)}>
            <Icon className={cn("w-8 h-8", config.text)} />
          </div>
          
          <div className="flex-1 min-w-0">
            <div className={cn("text-xs font-semibold uppercase tracking-wider mb-1", config.text)}>
              Verdict
            </div>
            <h3 className={cn("text-xl font-bold mb-1", config.text)}>
              {config.label}
            </h3>
            <p className={cn("text-sm mb-4", config.text, "opacity-80")}>
              {config.description}
            </p>
            <div className="mb-5 flex flex-col sm:flex-row sm:items-center gap-4 rounded-xl border border-black/10 bg-white/60 p-4">
              <div className="relative h-24 w-24 flex-shrink-0">
                <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
                  <circle cx="50" cy="50" r={radius} className="fill-none stroke-black/10" strokeWidth="8" />
                  <circle
                    cx="50"
                    cy="50"
                    r={radius}
                    className="fill-none transition-all duration-700 ease-out"
                    style={{ stroke: config.ringColor }}
                    strokeWidth="8"
                    strokeLinecap="round"
                    strokeDasharray={circumference}
                    strokeDashoffset={offset}
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <p className={cn("text-lg font-bold leading-none", config.text)}>{confidence}%</p>
                  <p className="text-[10px] uppercase tracking-wider text-foreground-muted">Confidence</p>
                </div>
              </div>
              <div>
                <p className={cn("text-sm font-semibold", config.text)}>Confidence score</p>
                <p className="text-xs text-foreground-muted">
                  Percentage reflects consistency and quality of evidence used in synthesis.
                </p>
              </div>
            </div>

            {verdict.verdict_reasoning && (
              <p className={cn("text-sm leading-relaxed", config.text)}>
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
    <Card className="bg-mixed-bg border-mixed/30">
      <CardContent className="p-4 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
        <div>
          <div className="text-xs font-semibold text-amber-700 uppercase tracking-wider mb-1">
            Demographic Note
          </div>
          <p className="text-sm text-amber-800">{text}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export { VerdictCard, DemographicCaveat };
