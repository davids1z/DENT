import type { Metadata } from "next";
import { Fraunces, Syne, Outfit, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { MobileNav } from "@/components/MobileNav";
import { Footer } from "@/components/Footer";
import { AuthProvider } from "@/lib/auth";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ScrollProvider } from "@/components/ScrollProvider";
import { PageTracker } from "@/components/PageTracker";

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin", "latin-ext"],
  display: "swap",
  weight: ["400", "500", "700", "800", "900"],
});

const syne = Syne({
  variable: "--font-syne",
  subsets: ["latin", "latin-ext"],
  display: "swap",
  weight: ["600", "700", "800"],
});

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin", "latin-ext"],
  display: "swap",
  weight: ["300", "400", "500", "600", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin", "latin-ext"],
  display: "swap",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "DENT - Detekcija prijevara i forenzička verifikacija",
  description:
    "AI platforma za detekciju prijevara, forenzičku analizu slika i dokumenata, prepoznavanje AI-generiranog sadržaja i kriptografsku verifikaciju dokaza.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="hr" suppressHydrationWarning>
      <head>
        <meta name="theme-color" content="#0f172a" media="(prefers-color-scheme: dark)" />
        <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)" />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var d=document.documentElement;var t=localStorage.getItem("dent_theme");var isDark=t==="dark"||(t!=="light"&&window.matchMedia("(prefers-color-scheme:dark)").matches);if(isDark){d.classList.add("dark");d.style.colorScheme="dark"}if(document.cookie.indexOf("dent_has_auth=1")!==-1)d.dataset.auth="1"}catch(e){}})()`,
          }}
        />
      </head>
      <body
        className={`${fraunces.variable} ${syne.variable} ${outfit.variable} ${jetbrainsMono.variable} antialiased bg-background text-foreground`}
        style={{ paddingTop: "env(safe-area-inset-top)", paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <AuthProvider>
          <ScrollProvider>
            <Navbar />
            <main className="min-h-[calc(100dvh-56px)] pb-20 md:pb-0">
              <ErrorBoundary>
                {children}
              </ErrorBoundary>
            </main>
            <Footer />
            <MobileNav />
            <PageTracker />
          </ScrollProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
