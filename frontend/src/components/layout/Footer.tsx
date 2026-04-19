function Footer() {
  return (
    <footer className="border-t border-border bg-surface mt-auto py-6">
      <div className="max-w-5xl mx-auto px-4 sm:px-6">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-foreground-muted">
          <p>NutriEvidence by Health Myth Debunker</p>
          <p>Data sourced from PubMed/NCBI</p>
        </div>
      </div>
    </footer>
  );
}

export { Footer };
