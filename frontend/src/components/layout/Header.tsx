import { Search, ArrowRight, Shield } from "lucide-react";

interface HeaderProps {
  onAnalyzeClick?: () => void;
}

function Header({ onAnalyzeClick }: HeaderProps) {
  return (
    <header className="border-b border-border bg-surface">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4">
        <div className="flex items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 bg-surface-muted rounded-lg border border-border">
              <Shield className="w-5 h-5 text-primary" />
            </div>
            <div>
              <span className="text-xl font-semibold tracking-tight text-foreground">
                Nutri<span className="text-primary">Evidence</span>
              </span>
            </div>
          </div>

          {/* Navigation - Desktop */}
          <nav className="hidden md:flex items-center gap-8">
            <a href="#protocol" className="text-xs font-medium tracking-widest text-foreground-muted hover:text-foreground transition-colors uppercase">
              Analysis Protocol
            </a>
            <a href="#database" className="text-xs font-medium tracking-widest text-foreground-muted hover:text-foreground transition-colors uppercase">
              Bio-Evidence Database
            </a>
            <a href="#about" className="text-xs font-medium tracking-widest text-foreground-muted hover:text-foreground transition-colors uppercase">
              About
            </a>
          </nav>

          {/* CTA Button */}
          <button
            onClick={onAnalyzeClick}
            className="hidden sm:flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-foreground border border-border rounded-full hover:bg-surface-muted transition-all duration-200"
          >
            Verify a Claim
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
}

export { Header };
