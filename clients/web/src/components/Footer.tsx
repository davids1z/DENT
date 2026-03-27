import Link from "next/link";

export function Footer() {
  return (
    <footer className="border-t border-border bg-background">
      <div className="max-w-7xl mx-auto px-4 sm:px-6">
        <div className="py-12 grid grid-cols-2 md:grid-cols-4 gap-8">
          {/* Brand */}
          <div className="col-span-2 md:col-span-1">
            <Link href="/" className="flex items-center gap-2.5 mb-4">
              <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center text-white font-bold text-sm">
                D
              </div>
              <span className="font-heading font-bold text-lg tracking-tight">
                DENT
              </span>
            </Link>
            <p className="text-sm text-muted leading-relaxed max-w-xs">
              AI platforma za detekciju prijevara, forenzičku verifikaciju
              slika i dokumenata.
            </p>
          </div>

          {/* Product */}
          <div>
            <h4 className="font-heading font-semibold text-sm mb-4">
              Proizvod
            </h4>
            <ul className="space-y-2.5">
              <li>
                <Link
                  href="/inspect"
                  className="text-sm text-muted hover:text-foreground transition-colors"
                >
                  Nova analiza
                </Link>
              </li>
              <li>
                <Link
                  href="/inspections"
                  className="text-sm text-muted hover:text-foreground transition-colors"
                >
                  Analize
                </Link>
              </li>
              <li>
                <Link
                  href="/"
                  className="text-sm text-muted hover:text-foreground transition-colors"
                >
                  Dashboard
                </Link>
              </li>
            </ul>
          </div>

          {/* Capabilities */}
          <div>
            <h4 className="font-heading font-semibold text-sm mb-4">
              Mogućnosti
            </h4>
            <ul className="space-y-2.5">
              <li className="text-sm text-muted">Detekcija prijevara</li>
              <li className="text-sm text-muted">Forenzika slika</li>
              <li className="text-sm text-muted">AI-generirani sadržaj</li>
              <li className="text-sm text-muted">Forenzika dokumenata</li>
            </ul>
          </div>

          {/* Info */}
          <div>
            <h4 className="font-heading font-semibold text-sm mb-4">Info</h4>
            <ul className="space-y-2.5">
              <li className="text-sm text-muted">Verzija 1.0 Beta</li>
              <li className="text-sm text-muted">AI Forenzika</li>
              <li className="text-sm text-muted">GDPR sukladno</li>
            </ul>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="border-t border-border py-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs text-muted-light">
            &copy; {new Date().getFullYear()} DENT. Sva prava pridržana.
          </p>
          <div className="flex items-center gap-1.5 text-xs text-muted-light">
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"
              />
            </svg>
            Pogonjeno umjetnom inteligencijom
          </div>
        </div>
      </div>
    </footer>
  );
}
