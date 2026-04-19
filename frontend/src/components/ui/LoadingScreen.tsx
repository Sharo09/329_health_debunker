import { cn } from "../../lib/utils";

interface LoadingScreenProps {
  message?: string;
  submessage?: string;
  step?: number;
  totalSteps?: number;
}

function LoadingScreen({ 
  message = "Evaluating Health Narrative...", 
  submessage = "Extracting Claims & PICO Parameters",
  step,
  totalSteps 
}: LoadingScreenProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 animate-fade-in">
      {/* Brain Icon with Animation */}
      <div className="relative mb-8">
        {/* Outer glow */}
        <div className="absolute inset-0 w-24 h-24 bg-primary/10 rounded-full blur-xl animate-pulse" />
        
        {/* Icon container */}
        <div className="relative w-24 h-24 flex items-center justify-center animate-float">
          <svg 
            viewBox="0 0 64 64" 
            className="w-16 h-16 text-primary"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            {/* Brain outline */}
            <path d="M32 8c-8 0-14 6-14 14 0 4 1.5 7.5 4 10-2.5 2.5-4 6-4 10 0 8 6 14 14 14s14-6 14-14c0-4-1.5-7.5-4-10 2.5-2.5 4-6 4-10 0-8-6-14-14-14z" />
            {/* Neural connections */}
            <circle cx="26" cy="22" r="2" fill="currentColor" />
            <circle cx="38" cy="22" r="2" fill="currentColor" />
            <circle cx="32" cy="32" r="2" fill="currentColor" />
            <circle cx="26" cy="42" r="2" fill="currentColor" />
            <circle cx="38" cy="42" r="2" fill="currentColor" />
            <line x1="26" y1="22" x2="32" y2="32" />
            <line x1="38" y1="22" x2="32" y2="32" />
            <line x1="32" y1="32" x2="26" y2="42" />
            <line x1="32" y1="32" x2="38" y2="42" />
          </svg>
        </div>
        
        {/* Curved line decoration */}
        <svg className="absolute -bottom-4 left-1/2 -translate-x-1/2 w-12 h-6 text-primary" viewBox="0 0 48 24">
          <path 
            d="M0 0 Q24 24 48 0" 
            fill="none" 
            stroke="currentColor" 
            strokeWidth="2"
            className="animate-pulse"
          />
        </svg>
      </div>

      {/* Main Message */}
      <h2 className="text-2xl sm:text-3xl font-serif italic text-foreground mb-4 text-center">
        {message}
      </h2>

      {/* Animated Dots */}
      <div className="flex items-center gap-1.5 mb-4">
        {[0, 1, 2].map((i) => (
          <span 
            key={i}
            className="w-2 h-2 rounded-full bg-primary animate-bounce-dot"
            style={{ animationDelay: `${i * 0.16}s` }}
          />
        ))}
      </div>

      {/* Submessage */}
      <p className="text-xs font-medium tracking-widest text-foreground-muted uppercase">
        {submessage}
      </p>

      {/* Progress indicator */}
      {step !== undefined && totalSteps !== undefined && (
        <div className="mt-8 flex items-center gap-2">
          <span className="text-xs text-foreground-muted">Step {step} of {totalSteps}</span>
        </div>
      )}
    </div>
  );
}

export { LoadingScreen };
