import { History, Clock, ArrowRight, Trash2, Search } from "lucide-react";
import { Card, CardContent } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { cn } from "../../lib/utils";

interface HistoryEntry {
  id: string;
  claim: string;
  verdict?: "supported" | "contradicted" | "insufficient_evidence";
  papersCount: number;
  timestamp: Date;
}

interface HistoryTabProps {
  history: HistoryEntry[];
  onSelectEntry: (entry: HistoryEntry) => void;
  onClearHistory: () => void;
  onNewClaim: () => void;
}

const verdictConfig = {
  supported: { label: "Supported", variant: "supported" as const },
  contradicted: { label: "Contradicted", variant: "unsupported" as const },
  insufficient_evidence: { label: "Insufficient", variant: "insufficient" as const },
};

function formatTimeAgo(date: Date): string {
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
  
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return date.toLocaleDateString();
}

function HistoryTab({ history, onSelectEntry, onClearHistory, onNewClaim }: HistoryTabProps) {
  if (history.length === 0) {
    return (
      <div className="animate-fade-in">
        {/* Empty State */}
        <div className="text-center py-16">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-muted mb-6">
            <History className="w-8 h-8 text-foreground-muted" />
          </div>
          
          <h2 className="text-xl font-semibold text-foreground mb-3">
            No search history yet
          </h2>
          
          <p className="text-foreground-muted max-w-md mx-auto mb-6">
            Your analyzed claims will appear here so you can easily revisit them later.
          </p>
          
          <Button onClick={onNewClaim}>
            <Search className="w-4 h-4" />
            Analyze Your First Claim
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold text-foreground">Search History</h2>
          <p className="text-sm text-foreground-muted mt-1">
            {history.length} claim{history.length === 1 ? "" : "s"} analyzed
          </p>
        </div>
        
        <Button variant="ghost" onClick={onClearHistory} className="text-foreground-muted hover:text-unsupported">
          <Trash2 className="w-4 h-4" />
          Clear All
        </Button>
      </div>

      {/* History List */}
      <div className="space-y-3">
        {history.map((entry) => {
          const verdictDisplay = entry.verdict ? verdictConfig[entry.verdict] : null;
          
          return (
            <Card key={entry.id} className="hover:shadow-md transition-shadow duration-200">
              <CardContent className="p-4">
                <button
                  onClick={() => onSelectEntry(entry)}
                  className="w-full text-left flex items-start gap-4 group"
                >
                  <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-muted flex items-center justify-center">
                    <Clock className="w-5 h-5 text-foreground-muted" />
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-foreground group-hover:text-primary truncate transition-colors">
                      {entry.claim}
                    </p>
                    
                    <div className="flex items-center gap-3 mt-2">
                      {verdictDisplay && (
                        <Badge variant={verdictDisplay.variant}>
                          {verdictDisplay.label}
                        </Badge>
                      )}
                      <span className="text-xs text-foreground-muted">
                        {entry.papersCount} paper{entry.papersCount === 1 ? "" : "s"}
                      </span>
                      <span className="text-xs text-foreground-subtle">
                        {formatTimeAgo(entry.timestamp)}
                      </span>
                    </div>
                  </div>
                  
                  <ArrowRight className="w-5 h-5 text-foreground-subtle group-hover:text-primary opacity-0 group-hover:opacity-100 transition-all flex-shrink-0 mt-2" />
                </button>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Bottom hint */}
      <p className="text-center text-xs text-foreground-subtle mt-8">
        History is stored locally in your browser
      </p>
    </div>
  );
}

export { HistoryTab };
export type { HistoryEntry };
