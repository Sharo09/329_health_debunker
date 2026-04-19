import { Search, ArrowRight, Sparkles } from "lucide-react";
import { Card, CardContent } from "../ui/Card";
import { Badge } from "../ui/Badge";
import { cn } from "../../lib/utils";

interface CommonClaimsTabProps {
  onSelectClaim: (claim: string) => void;
}

interface ClaimCategory {
  name: string;
  icon: string;
  claims: Array<{
    text: string;
    popularity: "high" | "medium" | "low";
  }>;
}

const categories: ClaimCategory[] = [
  {
    name: "Inflammation & Joint Health",
    icon: "flame",
    claims: [
      { text: "Turmeric reduces inflammation", popularity: "high" },
      { text: "Fish oil helps with joint pain", popularity: "high" },
      { text: "Ginger has anti-inflammatory properties", popularity: "medium" },
      { text: "Cherries help with gout", popularity: "medium" },
    ],
  },
  {
    name: "Heart & Cardiovascular",
    icon: "heart",
    claims: [
      { text: "Omega-3 supplements improve heart health", popularity: "high" },
      { text: "Red wine is good for the heart", popularity: "high" },
      { text: "Garlic lowers blood pressure", popularity: "medium" },
      { text: "Oatmeal lowers cholesterol", popularity: "medium" },
    ],
  },
  {
    name: "Weight & Metabolism",
    icon: "scale",
    claims: [
      { text: "Green tea helps with weight loss", popularity: "high" },
      { text: "Apple cider vinegar boosts metabolism", popularity: "high" },
      { text: "Coconut oil burns fat", popularity: "medium" },
      { text: "Caffeine increases metabolism", popularity: "medium" },
    ],
  },
  {
    name: "Brain & Cognitive",
    icon: "brain",
    claims: [
      { text: "Blueberries improve memory", popularity: "high" },
      { text: "Coffee prevents cognitive decline", popularity: "medium" },
      { text: "Fish improves brain function", popularity: "medium" },
      { text: "Dark chocolate enhances focus", popularity: "low" },
    ],
  },
  {
    name: "Immune System",
    icon: "shield",
    claims: [
      { text: "Vitamin C prevents colds", popularity: "high" },
      { text: "Honey has antibacterial properties", popularity: "medium" },
      { text: "Elderberry boosts immunity", popularity: "medium" },
      { text: "Garlic fights infections", popularity: "low" },
    ],
  },
  {
    name: "Sleep & Relaxation",
    icon: "moon",
    claims: [
      { text: "Chamomile tea improves sleep", popularity: "high" },
      { text: "Warm milk helps you sleep", popularity: "medium" },
      { text: "Bananas help with relaxation", popularity: "low" },
      { text: "Tart cherry juice improves sleep quality", popularity: "medium" },
    ],
  },
];

const popularityColors = {
  high: "bg-primary/10 text-primary",
  medium: "bg-foreground-muted/10 text-foreground-muted",
  low: "bg-foreground-subtle/10 text-foreground-subtle",
};

function CommonClaimsTab({ onSelectClaim }: CommonClaimsTabProps) {
  return (
    <div className="animate-fade-in">
      {/* Header */}
      <section className="text-center py-8">
        <div className="inline-flex items-center gap-2 bg-accent/10 text-accent-dark px-4 py-1.5 rounded-full text-sm font-medium mb-4">
          <Sparkles className="w-4 h-4" />
          Popular Topics
        </div>
        <h2 className="text-2xl sm:text-3xl font-bold text-foreground mb-3 text-balance">
          Explore Common Nutrition Claims
        </h2>
        <p className="text-foreground-muted max-w-xl mx-auto">
          Click on any claim below to analyze it with peer-reviewed scientific evidence.
        </p>
      </section>

      {/* Categories Grid */}
      <div className="grid gap-6 md:grid-cols-2">
        {categories.map((category) => (
          <Card key={category.name} variant="elevated">
            <CardContent className="p-5">
              <h3 className="font-semibold text-foreground mb-4 flex items-center gap-2">
                <span className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                  <Search className="w-4 h-4 text-primary" />
                </span>
                {category.name}
              </h3>
              
              <div className="space-y-2">
                {category.claims.map((claim) => (
                  <button
                    key={claim.text}
                    onClick={() => onSelectClaim(claim.text)}
                    className={cn(
                      "w-full text-left px-4 py-3 rounded-lg border border-border",
                      "flex items-center justify-between gap-3 group",
                      "hover:border-primary hover:bg-primary/5 transition-all duration-200"
                    )}
                  >
                    <span className="text-sm text-foreground group-hover:text-primary">
                      {claim.text}
                    </span>
                    <div className="flex items-center gap-2">
                      <Badge className={cn("text-xs", popularityColors[claim.popularity])}>
                        {claim.popularity === "high" ? "Popular" : claim.popularity === "medium" ? "Common" : "Niche"}
                      </Badge>
                      <ArrowRight className="w-4 h-4 text-foreground-subtle group-hover:text-primary opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Bottom CTA */}
      <div className="text-center mt-10 py-8 border-t border-border">
        <p className="text-foreground-muted mb-2">
          Don&apos;t see your claim?
        </p>
        <button
          onClick={() => onSelectClaim("")}
          className="text-primary hover:text-primary-dark font-medium inline-flex items-center gap-2"
        >
          Analyze your own claim
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

export { CommonClaimsTab };
