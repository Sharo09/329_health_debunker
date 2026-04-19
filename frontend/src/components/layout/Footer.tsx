import { ExternalLink } from "lucide-react";

function Footer() {
  return (
    <footer className="border-t border-border bg-surface mt-auto py-8">
      <div className="max-w-6xl mx-auto px-4 sm:px-6">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-foreground-muted">
          <div className="flex items-center gap-2">
            <span className="font-medium text-foreground">NutriEvidence</span>
            <span className="text-foreground-subtle">by Health Myth Debunker</span>
          </div>
          <div className="flex items-center gap-6">
            <a 
              href="https://pubmed.ncbi.nlm.nih.gov/"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 hover:text-primary transition-colors"
            >
              Data sourced from PubMed/NCBI
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}

export { Footer };
