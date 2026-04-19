import { Leaf, ShieldCheck } from "lucide-react";

function Header() {
  return (
    <header className="border-b border-border/80 bg-surface/90 backdrop-blur-sm">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-10 h-10 bg-primary/10 rounded-xl">
              <Leaf className="w-6 h-6 text-primary" />
            </div>
            <div>
              <h1 className="text-2xl font-[family-name:var(--font-display)] font-semibold tracking-tight text-foreground">
                NutriEvidence
              </h1>
              <p className="text-xs text-foreground-muted hidden sm:block">
                Trusted nutrition claim verification
              </p>
            </div>
          </div>
          <div className="hidden sm:flex items-center gap-2 text-xs text-foreground-muted bg-muted rounded-full px-3 py-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-supported" />
            <span>Evidence-backed, not medical advice</span>
          </div>
        </div>
      </div>
    </header>
  );
}

export { Header };
