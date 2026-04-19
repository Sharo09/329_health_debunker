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
  },
  contradicted: {
    label: "Contradicted by Evidence",
    description: "The research literature contradicts this claim",
    icon: XCircle,
    bg: "bg-unsupported-bg",
    border: "border-unsupported/30",
    text: "text-red-800",
    bar: "bg-unsupported",
  },
  insufficient_evidence: {
    label: "Insufficient Evidence",
    description: "Not enough research to draw a firm conclusion",
    icon: HelpCircle,
    bg: "bg-insufficient-bg",
    border: "border-insufficient/30",
    text: "text-gray-700",
    bar: "bg-insufficient",
  },
};

function VerdictCard({ verdict }: VerdictCardProps) {
  const config = verdictConfig[verdict.verdict];
  const Icon = config.icon;
  const confidence = Math.round(verdict.confidence_percent);

  return (
    <Card className={cn("overflow-hidden", config.bg, config.border)}>
      <CardContent className="p-6">
        <div className="flex items-start gap-4">
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

            {/* Confidence Bar */}
            <div className="mb-4">
              <div className={cn("flex justify-between text-xs mb-1.5", config.text)}>
                <span>Confidence Level</span>
                <span className="font-semibold">{confidence}%</span>
              </div>
              <div className="h-2 bg-black/10 rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all duration-700 ease-out", config.bar)}
                  style={{ width: `${confidence}%` }}
                />
              </div>
            </div>

            {/* Reasoning */}
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
