import { ChevronRight, Flame, Heart, Scale, Brain, Shield, Moon } from "lucide-react";
import { Card, CardContent } from "../ui/Card";
import { cn } from "../../lib/utils";

interface CommonClaimsTabProps {
  onSelectClaim: (claim: string) => void;
}

interface ClaimCategory {
  name: string;
  icon: typeof Flame;
  claims: Array<{
    text: string;
    popularity: "high" | "medium" | "low";
  }>;
}

const categories: ClaimCategory[] = [
  {
    name: "Inflammation & Joint Health",
    icon: Flame,
    claims: [
      { text: "Turmeric reduces inflammation", popularity: "high" },
      { text: "Fish oil helps with joint pain", popularity: "high" },
      { text: "Ginger has anti-inflammatory properties", popularity: "medium" },
      { text: "Cherries help with gout", popularity: "medium" },
    ],
  },
  {
    name: "Heart & Cardiovascular",
    icon: Heart,
    claims: [
      { text: "Omega-3 supplements improve heart health", popularity: "high" },
      { text: "Red wine is good for the heart", popularity: "high" },
      { text: "Garlic lowers blood pressure", popularity: "medium" },
      { text: "Oatmeal lowers cholesterol", popularity: "medium" },
    ],
  },
  {
    name: "Weight & Metabolism",
    icon: Scale,
    claims: [
      { text: "Green tea helps with weight loss", popularity: "high" },
      { text: "Apple cider vinegar boosts metabolism", popularity: "high" },
      { text: "Coconut oil burns fat", popularity: "medium" },
      { text: "Caffeine increases metabolism", popularity: "medium" },
    ],
  },
  {
    name: "Brain & Cognitive",
    icon: Brain,
    claims: [
      { text: "Blueberries improve memory", popularity: "high" },
      { text: "Coffee prevents cognitive decline", popularity: "medium" },
      { text: "Fish improves brain function", popularity: "medium" },
      { text: "Dark chocolate enhances focus", popularity: "low" },
    ],
  },
  {
    name: "Immune System",
    icon: Shield,
    claims: [
      { text: "Vitamin C prevents colds", popularity: "high" },
      { text: "Honey has antibacterial properties", popularity: "medium" },
      { text: "Elderberry boosts immunity", popularity: "medium" },
      { text: "Garlic fights infections", popularity: "low" },
    ],
  },
  {
    name: "Sleep & Relaxation",
    icon: Moon,
    claims: [
      { text: "Chamomile tea improves sleep", popularity: "high" },
      { text: "Warm milk helps you sleep", popularity: "medium" },
      { text: "Bananas help with relaxation", popularity: "low" },
      { text: "Tart cherry juice improves sleep quality", popularity: "medium" },
    ],
  },
];

function CommonClaimsTab({ onSelectClaim }: CommonClaimsTabProps) {
  return (
    <div className="animate-fade-in">
      {/* Header */}
      <section className="text-center py-10">
        <span className="inline-flex items-center gap-2 bg-surface-muted border border-border px-4 py-2 rounded-full text-xs font-medium tracking-widest text-foreground-muted mb-6">
          <span className="w-2 h-2 rounded-full bg-primary"></span>
          POPULAR TOPICS
        </span>
        
        <h2 className="text-3xl sm:text-4xl font-serif text-foreground mb-4">
          Explore Common <span className="italic text-primary">Claims</span>
        </h2>
        <p className="text-foreground-muted max-w-xl mx-auto">
          Click on any claim below to analyze it with peer-reviewed scientific evidence.
        </p>
      </section>

      {/* Categories Grid */}
      <div className="grid gap-6 md:grid-cols-2">
        {categories.map((category) => {
          const Icon = category.icon;
          return (
            <Card key={category.name} className="border-0 bg-surface-muted rounded-2xl overflow-hidden">
              <CardContent className="p-6">
                <h3 className="font-semibold text-foreground mb-5 flex items-center gap-3">
                  <span className="w-10 h-10 rounded-xl bg-surface border border-border flex items-center justify-center">
                    <Icon className="w-5 h-5 text-primary" />
                  </span>
                  {category.name}
                </h3>
                
                <div className="space-y-2">
                  {category.claims.map((claim) => (
                    <button
                      key={claim.text}
                      onClick={() => onSelectClaim(claim.text)}
                      className={cn(
                        "w-full text-left px-4 py-3.5 rounded-xl bg-surface border border-border",
                        "flex items-center justify-between gap-3 group",
                        "hover:border-primary hover:shadow-sm transition-all duration-200"
                      )}
                    >
                      <span className="text-sm text-foreground-muted group-hover:text-foreground">
                        {claim.text}
                      </span>
                      <div className={cn(
                        "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 transition-all duration-200",
                        "border border-border group-hover:border-primary group-hover:bg-primary group-hover:text-surface"
                      )}>
                        <ChevronRight className="w-4 h-4 text-foreground-subtle group-hover:text-surface" />
                      </div>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Bottom CTA */}
      <div className="text-center mt-12 py-8 border-t border-border">
        <p className="text-foreground-muted mb-3">
          Don&apos;t see your claim?
        </p>
        <button
          onClick={() => onSelectClaim("")}
          className="text-primary hover:text-primary-dark font-medium inline-flex items-center gap-2 px-6 py-2.5 rounded-full border border-primary hover:bg-primary hover:text-surface transition-all duration-200"
        >
          Analyze your own claim
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

export { CommonClaimsTab };
