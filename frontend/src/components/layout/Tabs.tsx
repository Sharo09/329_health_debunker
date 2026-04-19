import { cn } from "../../lib/utils";
import { Search, FileText, History, BookOpen, Info } from "lucide-react";

export type TabId = "analyze" | "common" | "history" | "results" | "about";

interface Tab {
  id: TabId;
  label: string;
  icon: typeof Search;
}

const tabs: Tab[] = [
  { id: "analyze", label: "Analyze Claim", icon: Search },
  { id: "common", label: "Common Claims", icon: FileText },
  { id: "history", label: "History", icon: History },
  { id: "results", label: "Results", icon: BookOpen },
  { id: "about", label: "About", icon: Info },
];

interface TabsProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  hasResults?: boolean;
}

function Tabs({ activeTab, onTabChange, hasResults }: TabsProps) {
  return (
    <nav className="bg-surface border-b border-border sticky top-0 z-10">
      <div className="max-w-5xl mx-auto px-4 sm:px-6">
        <div className="flex gap-1 overflow-x-auto scrollbar-hide -mb-px">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;
            const isDisabled = tab.id === "results" && !hasResults;
            const Icon = tab.icon;
            
            return (
              <button
                key={tab.id}
                onClick={() => !isDisabled && onTabChange(tab.id)}
                disabled={isDisabled}
                className={cn(
                  "flex items-center gap-2 px-4 py-3 text-sm font-medium whitespace-nowrap transition-all duration-200 border-b-2 -mb-px",
                  isActive
                    ? "text-primary border-primary"
                    : "text-foreground-muted border-transparent hover:text-foreground hover:border-border",
                  isDisabled && "opacity-40 cursor-not-allowed"
                )}
              >
                <Icon className="w-4 h-4" />
                <span className="hidden sm:inline">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
}

export { Tabs };
