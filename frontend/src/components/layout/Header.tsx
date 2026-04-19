import { Leaf, FlaskConical } from "lucide-react";

function Header() {
  return (
    <header className="bg-primary text-white">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 bg-accent/20 rounded-lg">
            <Leaf className="w-6 h-6 text-accent" />
          </div>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight">NutriEvidence</h1>
            <p className="text-sm text-white/70 hidden sm:block">Science-backed nutrition claim verification</p>
          </div>
        </div>
        
        <div className="mt-4 flex items-center gap-2 text-xs text-white/60 bg-white/5 rounded-lg px-3 py-2 w-fit">
          <FlaskConical className="w-3.5 h-3.5" />
          <span>Academic research tool — not medical advice</span>
        </div>
      </div>
    </header>
  );
}

export { Header };
