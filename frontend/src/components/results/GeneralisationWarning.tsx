import { AlertTriangle } from "lucide-react";
import { Card, CardContent } from "../ui/Card";

interface GeneralisationWarningProps {
  warnings: string[];
}

/**
 * Yellow-accented panel listing generalisation warnings surfaced by
 * Station 4 (Elicitation Patch B). Rendered between the VerdictCard
 * and the StratifiedEvidence block.
 *
 * Renders null when there are no warnings so the parent can mount it
 * unconditionally.
 */
function GeneralisationWarning({ warnings }: GeneralisationWarningProps) {
  if (!warnings || warnings.length === 0) return null;
  return (
    <Card
      variant="outline"
      className="border-amber-300 bg-mixed-bg"
    >
      <CardContent className="p-5">
        <div className="flex items-center gap-2 text-amber-900 mb-3">
          <AlertTriangle className="w-5 h-5" />
          <p className="text-xs font-bold uppercase tracking-wider">
            Generalisation warnings
          </p>
        </div>
        <ul className="space-y-2 text-sm text-amber-900 leading-relaxed list-disc pl-5">
          {warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export { GeneralisationWarning };
