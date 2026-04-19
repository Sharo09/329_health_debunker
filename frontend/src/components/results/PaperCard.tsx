import { useState } from "react";
import { ExternalLink, ChevronDown, ChevronUp, AlertTriangle, Users } from "lucide-react";
import { Card, CardContent } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { cn } from "../../lib/utils";
import type { CitedPaper, Paper } from "../../api";

// For cited papers with stance
interface CitedPaperCardProps {
  paper: CitedPaper;
}

const stanceConfig = {
  supports: { variant: "supported" as const, label: "Supports" },
  contradicts: { variant: "unsupported" as const, label: "Contradicts" },
  neutral: { variant: "default" as const, label: "Neutral" },
  unclear: { variant: "mixed" as const, label: "Unclear" },
};

function CitedPaperCard({ paper }: CitedPaperCardProps) {
  const stance = stanceConfig[paper.stance] || stanceConfig.unclear;
  const relevance = Math.round(paper.relevance_score * 100);

  return (
    <Card className="border-0 bg-surface-muted rounded-2xl hover:shadow-md transition-all duration-200">
      <CardContent className="p-5">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <Badge variant={stance.variant}>{stance.label}</Badge>
          <Badge variant="outline">{relevance}% relevant</Badge>
          {paper.demographic_match && (
            <Badge variant="supported" className="gap-1">
              <Users className="w-3 h-3" />
              Demographic Match
            </Badge>
          )}
        </div>

        <h4 className="font-semibold text-foreground mb-2 leading-snug">
          {paper.url ? (
            <a
              href={paper.url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-primary inline-flex items-start gap-1.5 group"
            >
              <span className="group-hover:underline">{paper.title}</span>
              <ExternalLink className="w-3.5 h-3.5 flex-shrink-0 mt-1 opacity-50 group-hover:opacity-100" />
            </a>
          ) : (
            paper.title
          )}
        </h4>

        {paper.one_line_summary && (
          <p className="text-sm text-foreground-muted leading-relaxed mb-3">
            {paper.one_line_summary}
          </p>
        )}

        <p className="text-xs text-foreground-subtle">
          PMID: {paper.paper_id}
        </p>
      </CardContent>
    </Card>
  );
}

// For raw papers from retrieval
interface RawPaperCardProps {
  paper: Paper;
}

function RawPaperCard({ paper }: RawPaperCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card className={cn(
      "border-0 rounded-2xl hover:shadow-md transition-all duration-200",
      paper.is_retracted ? "bg-mixed-bg" : "bg-surface-muted"
    )}>
      <CardContent className="p-5">
        {paper.is_retracted && (
          <Badge variant="unsupported" className="gap-1 mb-3">
            <AlertTriangle className="w-3 h-3" />
            RETRACTED
          </Badge>
        )}

        <h4 className="font-semibold text-foreground mb-2 leading-snug">
          <a
            href={paper.pubmed_url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-primary inline-flex items-start gap-1.5 group"
          >
            <span className="group-hover:underline">{paper.title}</span>
            <ExternalLink className="w-3.5 h-3.5 flex-shrink-0 mt-1 opacity-50 group-hover:opacity-100" />
          </a>
        </h4>

        <div className="flex flex-wrap items-center gap-2 text-sm text-foreground-muted mb-3">
          <span>{paper.journal}</span>
          {paper.pub_year && (
            <>
              <span className="text-border">|</span>
              <span>{paper.pub_year}</span>
            </>
          )}
          {paper.pub_types.length > 0 && (
            <Badge variant="supported" className="text-xs">
              {paper.pub_types[0]}
            </Badge>
          )}
        </div>

        {paper.abstract && (
          <>
            <p className="text-sm text-foreground-muted leading-relaxed">
              {expanded ? paper.abstract : paper.abstract.slice(0, 200) + (paper.abstract.length > 200 ? "..." : "")}
            </p>
            {paper.abstract.length > 200 && (
              <button
                onClick={() => setExpanded(!expanded)}
                className="mt-3 text-sm text-primary hover:text-primary-dark font-medium inline-flex items-center gap-1"
              >
                {expanded ? (
                  <>
                    Show less <ChevronUp className="w-4 h-4" />
                  </>
                ) : (
                  <>
                    Read more <ChevronDown className="w-4 h-4" />
                  </>
                )}
              </button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

export { CitedPaperCard, RawPaperCard };
