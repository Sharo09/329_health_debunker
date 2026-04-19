import { 
  Leaf, 
  Search, 
  FileText, 
  Brain, 
  Shield, 
  ExternalLink, 
  BookOpen, 
  Users, 
  AlertTriangle,
  CheckCircle2,
  GraduationCap
} from "lucide-react";
import { Card, CardContent } from "../ui/Card";
import { cn } from "../../lib/utils";

function AboutTab() {
  return (
    <div className="animate-fade-in max-w-3xl mx-auto">
      {/* Hero Section */}
      <section className="text-center py-10">
        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-6">
          <Leaf className="w-8 h-8 text-primary" />
        </div>
        
        <h2 className="text-3xl font-bold text-foreground mb-4 text-balance">
          About NutriEvidence
        </h2>
        
        <p className="text-lg text-foreground-muted max-w-xl mx-auto leading-relaxed">
          A research tool that helps you verify nutrition and food health claims 
          using peer-reviewed scientific literature from PubMed.
        </p>
      </section>

      {/* How It Works */}
      <section className="mb-12">
        <h3 className="text-xl font-semibold text-foreground mb-6 text-center">
          How It Works
        </h3>
        
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            {
              icon: Search,
              step: "1",
              title: "Enter Your Claim",
              description: "Type any food or nutrition health claim you want to verify",
            },
            {
              icon: FileText,
              step: "2",
              title: "Answer Questions",
              description: "Provide context to help us find the most relevant research",
            },
            {
              icon: Brain,
              step: "3",
              title: "Get Evidence",
              description: "Receive a verdict backed by peer-reviewed scientific papers",
            },
          ].map((item) => (
            <Card key={item.step} className="text-center">
              <CardContent className="p-6">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-accent/10 mb-4">
                  <item.icon className="w-6 h-6 text-accent" />
                </div>
                <div className="text-xs font-semibold text-accent mb-2">Step {item.step}</div>
                <h4 className="font-semibold text-foreground mb-2">{item.title}</h4>
                <p className="text-sm text-foreground-muted">{item.description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Data Sources */}
      <section className="mb-12">
        <Card variant="elevated">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-12 h-12 rounded-xl bg-blue-100 flex items-center justify-center">
                <BookOpen className="w-6 h-6 text-blue-600" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-foreground mb-2">
                  Powered by PubMed
                </h3>
                <p className="text-foreground-muted mb-4">
                  We search the National Library of Medicine&apos;s PubMed database, which contains 
                  over 35 million citations for biomedical literature. This includes peer-reviewed 
                  research from medical journals, clinical trials, and systematic reviews.
                </p>
                <a
                  href="https://pubmed.ncbi.nlm.nih.gov/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm text-primary hover:text-primary-dark font-medium"
                >
                  Visit PubMed
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      {/* Evidence Levels */}
      <section className="mb-12">
        <h3 className="text-xl font-semibold text-foreground mb-6 text-center">
          Understanding Verdicts
        </h3>
        
        <div className="space-y-3">
          {[
            {
              icon: CheckCircle2,
              title: "Supported",
              description: "Multiple high-quality studies support this claim",
              bg: "bg-supported-bg",
              iconColor: "text-supported",
            },
            {
              icon: AlertTriangle,
              title: "Contradicted",
              description: "Research evidence contradicts or refutes this claim",
              bg: "bg-unsupported-bg",
              iconColor: "text-unsupported",
            },
            {
              icon: Shield,
              title: "Insufficient Evidence",
              description: "Not enough high-quality research to make a determination",
              bg: "bg-insufficient-bg",
              iconColor: "text-insufficient",
            },
          ].map((item) => (
            <Card key={item.title} className={cn("border-0", item.bg)}>
              <CardContent className="p-4 flex items-center gap-4">
                <item.icon className={cn("w-6 h-6 flex-shrink-0", item.iconColor)} />
                <div>
                  <h4 className="font-semibold text-foreground">{item.title}</h4>
                  <p className="text-sm text-foreground-muted">{item.description}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Limitations */}
      <section className="mb-12">
        <Card className="bg-mixed-bg border-mixed/30">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <AlertTriangle className="w-6 h-6 text-amber-600 flex-shrink-0" />
              <div>
                <h3 className="text-lg font-semibold text-amber-800 mb-2">
                  Important Limitations
                </h3>
                <ul className="space-y-2 text-sm text-amber-800">
                  <li className="flex items-start gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-600 mt-1.5 flex-shrink-0" />
                    This tool is for educational and research purposes only
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-600 mt-1.5 flex-shrink-0" />
                    Results should not be considered medical advice
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-600 mt-1.5 flex-shrink-0" />
                    Always consult healthcare professionals for medical decisions
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-600 mt-1.5 flex-shrink-0" />
                    Scientific understanding evolves as new research emerges
                  </li>
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      {/* Target Audience */}
      <section className="mb-12">
        <h3 className="text-xl font-semibold text-foreground mb-6 text-center">
          Who Is This For?
        </h3>
        
        <div className="grid gap-4 sm:grid-cols-2">
          {[
            {
              icon: Users,
              title: "Health-Conscious Individuals",
              description: "Anyone who wants to make informed decisions about nutrition claims they encounter",
            },
            {
              icon: GraduationCap,
              title: "Students & Researchers",
              description: "Those studying nutrition science or conducting academic research",
            },
          ].map((item) => (
            <Card key={item.title}>
              <CardContent className="p-5 flex items-start gap-4">
                <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                  <item.icon className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <h4 className="font-semibold text-foreground mb-1">{item.title}</h4>
                  <p className="text-sm text-foreground-muted">{item.description}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Footer */}
      <section className="text-center py-8 border-t border-border">
        <p className="text-sm text-foreground-muted">
          Built with care for evidence-based nutrition information.
        </p>
        <p className="text-xs text-foreground-subtle mt-2">
          Data sourced from NCBI/PubMed
        </p>
      </section>
    </div>
  );
}

export { AboutTab };
